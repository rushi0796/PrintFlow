import requests
import os
import json
import shutil
import hmac
import hashlib
import time
import threading
from typing import Optional
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from storage import (
    claim_order as durable_claim_order,
    complete_order as durable_complete_order,
    delete_document,
    get_document,
    get_order,
    get_queued_orders,
    list_orders as durable_list_orders,
    queue_paid_order,
    save_document,
    save_order,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
for env_candidate in [BASE_DIR / ".env", BASE_DIR / ".env.local"]:
    if env_candidate.exists():
        try:
            for line in env_candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

UPLOAD_DIR = (
    Path("/tmp/printflow-uploads")
    if os.environ.get("VERCEL")
    else BASE_DIR / "uploads"
)
UPLOAD_DIR.mkdir(exist_ok=True)

if UPLOAD_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

def load_orders():
    try:
        return durable_list_orders()
    except Exception as exc:
        print(f"[STORAGE LOAD ERROR] {type(exc).__name__}: {exc}")
        return []

def save_orders(orders):
    for order in orders:
        try:
            save_order(order)
        except Exception:
            pass

orders_db = load_orders()

@app.get("/")
def home():
    return {
        "app": "PrintFlow",
        "status": "Backend running successfully",
        "active_orders": len(orders_db)
    }

@app.get("/health")
def health():
    return {
        "status": "online"
    }

# Centralized Canonical Pricing Rules
CANONICAL_PRICING = {
    "bw_single": 2.0,       # ₹2 / page
    "bw_double": 1.0,       # ₹1 / page
    "color_single": 6.0,    # ₹6 / page
    "color_double": None,   # REMOVED
    "micro_xerox_sheet": 3.0 # ₹3 / sheet
}

def calculate_order_amount(
    pages: int,
    copies: int,
    color_mode: str = "black_white",
    duplex: str = "single",
    print_mode: str = "standard",
    pages_per_sheet: int = 1
) -> float:
    pages = max(1, pages or 1)
    copies = max(1, copies or 1)
    pages_per_sheet = max(1, pages_per_sheet or 1)

    if print_mode == "micro_xerox" and pages_per_sheet > 1:
        import math
        sheets = math.ceil(pages / pages_per_sheet)
        return float(sheets * copies * CANONICAL_PRICING["micro_xerox_sheet"])

    if color_mode and color_mode.lower() in ("color", "colour"):
        return float(pages * copies * CANONICAL_PRICING["color_single"])
    else:
        if duplex in ("double", "duplex", "duplex_long", "duplex_short", "duplexlong", "duplexshort"):
            return float(pages * copies * CANONICAL_PRICING["bw_double"])
        else:
            return float(pages * copies * CANONICAL_PRICING["bw_single"])

class PrintOrder(BaseModel):
    file_name: str
    copies: int = 1
    pages: int = 1
    color_mode: str = "black_white"
    duplex: str = "single"
    binding: Optional[str] = None
    paper_size: str = "a4"
    orientation: str = "portrait"
    scale_mode: str = "fit"
    margins: str = "normal"
    print_mode: str = "standard"
    pages_per_sheet: int = 1
    page_order: str = "horizontal"
    customer_mobile: str = "Guest"
    amount: float = 2.0
    file_path: str = ""

class RazorpayOrderRequest(BaseModel):
    amount: float
    pages: Optional[int] = None
    copies: Optional[int] = None
    color_mode: Optional[str] = "black_white"
    duplex: Optional[str] = "single"
    binding: Optional[str] = None
    paper_size: Optional[str] = "a4"
    orientation: Optional[str] = "portrait"
    scale_mode: Optional[str] = "fit"
    margins: Optional[str] = "normal"
    print_mode: Optional[str] = "standard"
    pages_per_sheet: Optional[int] = 1
    page_order: Optional[str] = "horizontal"
    file_name: Optional[str] = "document.pdf"
    file_path: Optional[str] = ""
    customer_mobile: Optional[str] = "Guest"
    order_id: Optional[str] = None
    customer_id: Optional[str] = "CUST_001"
    currency: Optional[str] = "INR"

@app.get("/api/orders")
def get_all_orders(
    x_customer_mobile: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None)
):
    orders = load_orders()
    is_admin = (x_admin_token == "Admin@123")

    if is_admin:
        return {
            "status": "success",
            "total_orders": len(orders),
            "orders": orders
        }

    if x_customer_mobile and x_customer_mobile.strip():
        user_orders = [
            o for o in orders
            if str(o.get("customer_mobile", "")).strip() == x_customer_mobile.strip()
        ]
        return {
            "status": "success",
            "total_orders": len(user_orders),
            "orders": user_orders
        }

    return {
        "status": "success",
        "total_orders": 0,
        "orders": []
    }

@app.post("/print-order")
def create_print_order(order: PrintOrder):
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    color_mode_str = (order.color_mode or "black_white").lower()
    is_color = color_mode_str in ("color", "colour")

    if is_color:
        enforced_duplex = "single"
        enforced_binding = ""
    else:
        enforced_binding = (order.binding or "").lower()
        enforced_duplex = (order.duplex or "single").lower()
        if enforced_duplex in ("double", "duplex"):
            enforced_duplex = "duplex_short" if enforced_binding == "short_edge" else "duplex_long"

    calculated_amount = calculate_order_amount(
        order.pages, order.copies, "color" if is_color else "black_white", enforced_duplex, order.print_mode, order.pages_per_sheet
    )
    new_order = {
        "order_id": order_id,
        "file_name": order.file_name,
        "copies": order.copies,
        "pages": order.pages,
        "color_mode": "color" if is_color else "black_white",
        "duplex": enforced_duplex,
        "binding": enforced_binding,
        "paper_size": order.paper_size,
        "orientation": order.orientation,
        "scale_mode": "actual" if (order.scale_mode or "").lower() in ("actual", "actual_size") else "fit",
        "margins": order.margins,
        "print_mode": "micro_xerox" if (order.print_mode or "").lower() == "micro_xerox" else "standard",
        "pages_per_sheet": (order.pages_per_sheet or 1) if (order.print_mode or "").lower() == "micro_xerox" else 1,
        "page_order": order.page_order,
        "customer_mobile": order.customer_mobile,
        "amount": calculated_amount,
        "file_path": order.file_path,
        "paid": False,
        "status": "Pending",
        "document_status": "UPLOADED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_order(new_order)
    return {
        "status": "success",
        "message": "Print order created successfully",
        "order": new_order
    }

AGENT_STATE = {
    "last_seen": 0,
    "status": "OFFLINE",
    "printers": []
}

def schedule_secure_document_cleanup(order_id: str, delay_seconds: float = 2.5):
    def _cleanup_worker():
        time.sleep(delay_seconds)
        orders = load_orders()
        for order in orders:
            if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
                order["document_status"] = "DELETING"
                file_rel_path = order.get("file_path", "")
                if file_rel_path:
                    clean_name = Path(file_rel_path).name
                    if file_rel_path.startswith("/api/documents/"):
                        delete_document(clean_name)
                        print(f"[PRIVACY CLEANUP SUCCESS] Durable document '{clean_name}' for Order {order_id} deleted 2.5s after completion.")
                    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
                    if not file_rel_path.startswith("/api/documents/") and Path(clean_name).suffix.lower() in allowed_exts:
                        target_file = UPLOAD_DIR / clean_name
                        if target_file.exists() and target_file.is_file():
                            try:
                                target_file.unlink()
                                print(f"[PRIVACY CLEANUP SUCCESS] Document '{clean_name}' for Order {order_id} deleted from disk 2.5s after completion.")
                            except Exception as e:
                                print(f"[PRIVACY CLEANUP ERROR]: {e}")
                order["file_path"] = ""
                order["document_status"] = "DELETED"
                order["deleted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_order(order)
                break

    thread = threading.Thread(target=_cleanup_worker, daemon=True)
    thread.start()

def verify_agent_token(header_token: Optional[str]):
    expected_token = (os.environ.get("PRINT_AGENT_TOKEN") or "PF_AGENT_SECRET_TOKEN_2026").strip()
    if not header_token or header_token.strip() != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized PrintAgent Token")

def queue_order_for_printing(payload: dict):
    order_id = payload.get("print_order_id") or payload.get("razorpay_order_id") or payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing PrintFlow order ID for verified payment")
    
    order = get_order(order_id)
    if not order:
        orders = load_orders()
        for o in orders:
            if o.get("order_id") == order_id or o.get("razorpay_order_id") == order_id:
                order = o
                break

    if not order:
        raise HTTPException(status_code=404, detail=f"PrintFlow order {order_id} not found")

    order["status"] = "PRINT_QUEUED"
    order["document_status"] = "UPLOADED"
    order["paid"] = True

    # Color mode vs duplex defensive rule
    color_mode = str(payload.get("color_mode") or order.get("color_mode") or "black_white").lower()
    if color_mode in ("color", "colour"):
        order["color_mode"] = "color"
        order["duplex"] = "single"
        order["binding"] = ""
    else:
        order["color_mode"] = "black_white"
        binding = str(payload.get("binding") or order.get("binding") or "").lower()
        duplex = str(payload.get("duplex") or order.get("duplex") or "single").lower()
        if duplex in ("double", "duplex"):
            duplex = "duplex_short" if binding == "short_edge" else "duplex_long"
        order["duplex"] = duplex
        order["binding"] = binding

    for k, v in payload.items():
        if v is not None and k not in ("status", "document_status", "color_mode", "duplex", "binding"):
            order[k] = v

    order.setdefault("scale_mode", "fit")
    order.setdefault("paper_size", "a4")
    order.setdefault("orientation", "portrait")
    order.setdefault("margins", "normal")
    order.setdefault("print_mode", "standard")
    order.setdefault("pages_per_sheet", 1)
    order.setdefault("page_order", "horizontal")
    save_order(order)
    return order

@app.post("/api/agent/poll")
def agent_poll_endpoint(req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    AGENT_STATE["last_seen"] = time.time()
    AGENT_STATE["status"] = "ONLINE"
    if "printers" in req:
        AGENT_STATE["printers"] = req["printers"]

    try:
        queued_jobs = get_queued_orders()
    except Exception as exc:
        print(f"[POLL QUEUE ERROR] {type(exc).__name__}: {exc}")
        orders = load_orders()
        queued_jobs = [o for o in orders if o.get("status") == "PRINT_QUEUED"]

    return {
        "status": "success",
        "agent_status": "ONLINE",
        "jobs_count": len(queued_jobs),
        "jobs": queued_jobs
    }

@app.post("/api/agent/claim/{order_id}")
def agent_claim_job_endpoint(order_id: str, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    claimed_order = durable_claim_order(order_id)
    if claimed_order:
        return {
            "status": "success",
            "message": f"Order {order_id} claimed successfully",
            "order": claimed_order
        }

    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.get("status") == "PRINTING":
        raise HTTPException(status_code=409, detail=f"Order {order_id} is already claimed and currently PRINTING.")
    if order.get("status") == "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Order {order_id} has already been completed.")

    raise HTTPException(status_code=400, detail=f"Order {order_id} cannot be claimed in status {order.get('status')}.")

@app.post("/api/agent/complete/{order_id}")
def agent_complete_job_endpoint(order_id: str, req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = req.get("status", "COMPLETED")
    order["status"] = new_status
    if new_status == "COMPLETED":
        order["document_status"] = "PRINTED"
        order["printed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order["printed_by_printer"] = req.get("printed_by_printer", "Windows Printer")
        order["completed_at"] = datetime.utcnow().isoformat()
        save_order(order)
        schedule_secure_document_cleanup(order_id, 2.5)
    else:
        order["document_status"] = "UPLOADED"
        order["print_error"] = req.get("error", "Print execution failed")
        save_order(order)

    return {
        "status": "success",
        "message": f"Order {order_id} updated to {new_status}",
        "order": order
    }

@app.get("/api/orders/{order_id}")
@app.get("/api/orders/{order_id}/status")
def get_order_status_endpoint(
    order_id: str,
    x_customer_mobile: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None)
):
    matching_order = get_order(order_id)
    if not matching_order:
        raise HTTPException(status_code=404, detail="Order not found")

    order_mobile = matching_order.get("customer_mobile")
    is_admin = (x_admin_token == "Admin@123")

    if order_mobile and str(order_mobile).strip().lower() != "guest" and not is_admin:
        if not x_customer_mobile or x_customer_mobile.strip() != str(order_mobile).strip():
            raise HTTPException(status_code=403, detail="Access denied: Unauthorized order access")

    return {
        "status": "success",
        "order_id": order_id,
        "order_status": matching_order.get("status", "PRINT_QUEUED"),
        "document_status": matching_order.get("document_status", "UPLOADED"),
        "deleted": matching_order.get("document_status") == "DELETED",
        "order": matching_order
    }

@app.post("/api/logout")
def logout_endpoint(
    x_customer_mobile: Optional[str] = Header(None)
):
    return {
        "status": "success",
        "message": "Session invalidated successfully"
    }

@app.get("/api/agent/status")
def agent_status_endpoint():
    is_online = (time.time() - AGENT_STATE["last_seen"]) < 12
    return {
        "status": "success",
        "agent_online": is_online,
        "last_seen": AGENT_STATE["last_seen"],
        "discovered_printers": AGENT_STATE["printers"]
    }

@app.post("/api/create-order")
@app.post("/create-razorpay-order")
@app.post("/api/create-razorpay-order")
def create_razorpay_order_endpoint(request: RazorpayOrderRequest):
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "").strip().strip('"').strip("'")
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip().strip('"').strip("'")

    if not key_id or not key_secret:
        raise HTTPException(status_code=500, detail="Razorpay LIVE credentials are not configured")

    is_live_key = key_id.startswith("rzp_live_")
    mode_str = "LIVE" if is_live_key else "TEST"

    if request.amount >= 100:
        amount_in_paise = int(round(request.amount))
    else:
        amount_in_paise = int(round(request.amount * 100))

    if request.pages and request.copies and request.pages > 0 and request.copies > 0:
        expected_rupees = calculate_order_amount(
            request.pages, request.copies, request.color_mode, request.duplex, request.print_mode, request.pages_per_sheet
        )
        expected_paise = int(round(expected_rupees * 100))
        if amount_in_paise < expected_paise:
            amount_in_paise = expected_paise

    receipt_id = f"rcpt_{uuid4().hex[:12]}"
    try:
        rzp_url = "https://api.razorpay.com/v1/orders"
        rzp_payload = {
            "amount": amount_in_paise,
            "currency": request.currency or "INR",
            "receipt": receipt_id,
            "payment_capture": 1
        }
        headers = {
            "User-Agent": "Razorpay/v1 PythonSDK/1.4.0",
            "Accept": "application/json"
        }
        resp = requests.post(rzp_url, auth=HTTPBasicAuth(key_id, key_secret), headers=headers, json=rzp_payload, timeout=10)
        if resp.status_code not in (200, 201):
            try:
                razorpay_error = resp.json().get("error", {})
                detail = razorpay_error.get("description") or razorpay_error.get("reason") or resp.text
            except ValueError:
                detail = resp.text
            raise HTTPException(status_code=resp.status_code, detail=f"Razorpay order creation failed: {detail}")

        razorpay_order = resp.json()
        final_order_id = razorpay_order["id"]

        color_str = (request.color_mode or "black_white").lower()
        is_color = color_str in ("color", "colour")
        if is_color:
            enforced_duplex = "single"
            enforced_binding = ""
        else:
            enforced_binding = (request.binding or "").lower()
            enforced_duplex = (request.duplex or "single").lower()
            if enforced_duplex in ("double", "duplex"):
                enforced_duplex = "duplex_short" if enforced_binding == "short_edge" else "duplex_long"

        pf_order_id = request.order_id if (request.order_id and str(request.order_id).startswith("PF-")) else f"PF-{uuid4().hex[:6].upper()}"

        new_order_entry = {
            "order_id": pf_order_id,
            "razorpay_order_id": final_order_id,
            "file_name": request.file_name or "document.pdf",
            "file_path": request.file_path or "",
            "copies": request.copies or 1,
            "pages": request.pages or 1,
            "color_mode": "color" if is_color else "black_white",
            "duplex": enforced_duplex,
            "binding": enforced_binding,
            "paper_size": request.paper_size or "a4",
            "orientation": request.orientation or "portrait",
            "scale_mode": "actual" if (request.scale_mode or "").lower() in ("actual", "actual_size") else "fit",
            "margins": request.margins or "normal",
            "print_mode": "micro_xerox" if (request.print_mode or "").lower() == "micro_xerox" else "standard",
            "pages_per_sheet": (request.pages_per_sheet or 1) if (request.print_mode or "").lower() == "micro_xerox" else 1,
            "page_order": request.page_order or "horizontal",
            "customer_mobile": request.customer_mobile or "Guest",
            "amount": amount_in_paise / 100.0,
            "paid": False,
            "status": "Pending",
            "document_status": "UPLOADED",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_order(new_order_entry)
        if not get_order(pf_order_id):
            raise HTTPException(status_code=503, detail="PrintFlow could not persist the order before payment")

        return {
            "status": "success",
            "key_id": key_id,
            "order_id": final_order_id,
            "pf_order_id": pf_order_id,
            "print_order_id": pf_order_id,
            "amount": amount_in_paise,
            "currency": request.currency or "INR",
            "mode": mode_str
        }
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay order service unavailable: {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Invalid Razorpay order response: {exc}") from exc

@app.post("/api/verify-payment")
@app.post("/verify-razorpay-payment")
@app.post("/api/verify-razorpay-payment")
def verify_razorpay_payment(payload: dict):
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip().strip('"').strip("'")
    if not key_secret:
        raise HTTPException(status_code=400, detail="RAZORPAY_KEY_SECRET not configured in server environment variables.")

    razorpay_order_id = payload.get("razorpay_order_id", "")
    razorpay_payment_id = payload.get("razorpay_payment_id", "")
    razorpay_signature = payload.get("razorpay_signature", "")

    if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
        raise HTTPException(status_code=400, detail="Missing required payment verification fields")

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    generated_signature = hmac.new(
        key_secret.encode("utf-8"),
        msg,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature - payment verification failed")

    queued_order = queue_order_for_printing(payload)

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully. Job queued for PrintAgent.",
        "order_status": "PRINT_QUEUED",
        "order_id": queued_order.get("order_id") or payload.get("print_order_id") or razorpay_order_id,
        "order": queued_order,
        "payload": payload
    }

@app.post("/upload-pdf")
@app.post("/api/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")

        allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail=f"Unsupported file format '{file_ext}'")

        original_name = Path(file.filename).name
        content = await file.read()
        document_id = save_document(original_name, file.content_type or "application/octet-stream", content)
        returned_path = f"/api/documents/{document_id}"

        return {
            "status": "success",
            "message": "File uploaded successfully",
            "file_name": original_name,
            "file_path": returned_path
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{document_id}")
def download_document(document_id: str, x_print_agent_token: Optional[str] = Header(None)):
    if x_print_agent_token:
        verify_agent_token(x_print_agent_token)
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    import urllib.parse
    raw_name = Path(document.get("file_name", "document.pdf")).name
    ascii_name = raw_name.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_name or ascii_name.startswith("."):
        ascii_name = f"document{Path(raw_name).suffix or '.pdf'}"
    encoded_name = urllib.parse.quote(raw_name)
    content_disposition = f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'

    return Response(
        content=document["content"],
        media_type=document.get("mime_type", "application/octet-stream"),
        headers={"Content-Disposition": content_disposition}
    )

@app.post("/api/orders/{order_id}/retry")
def retry_order_endpoint(
    order_id: str,
    x_customer_mobile: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None)
):
    orders = load_orders()
    matching_order = None
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            matching_order = order
            break

    if matching_order:
        order_mobile = matching_order.get("customer_mobile")
        is_admin = (x_admin_token == "Admin@123")
        if order_mobile and not is_admin:
            if not x_customer_mobile or x_customer_mobile.strip() != str(order_mobile).strip():
                raise HTTPException(status_code=403, detail="Access denied: Unauthorized order access")

        matching_order["status"] = "PRINT_QUEUED"
        save_order(matching_order)
        return {
            "status": "success",
            "message": f"Order {order_id} reset to PRINT_QUEUED for retry",
            "order_status": "PRINT_QUEUED",
            "order": matching_order
        }

    retry_queued = {
        "order_id": order_id,
        "file_name": "document.pdf",
        "file_path": "/uploads/test.pdf",
        "color_mode": "black_white",
        "copies": 1,
        "pages": 1,
        "duplex": "single",
        "customer_mobile": x_customer_mobile or "",
        "status": "PRINT_QUEUED",
        "document_status": "UPLOADED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_order(retry_queued)
    return {
        "status": "success",
        "message": f"Order {order_id} queued for retry",
        "order_status": "PRINT_QUEUED",
        "order": retry_queued
    }
