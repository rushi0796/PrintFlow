import requests
import os
import json
import shutil
import hmac
import hashlib
from typing import Optional
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from storage import (
    claim_order as durable_claim_order,
    complete_order as durable_complete_order,
    delete_document,
    get_document,
    get_order,
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
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    except Exception as e:
        pass

def load_orders():
    return durable_list_orders()


def save_orders(orders):
    for order in orders:
        save_order(order)


orders_db = []

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

class PrintOrder(BaseModel):
    file_name: str
    copies: int = 1
    pages: int = 1
    file_size: int = 0
    paper_size: str = "A4"
    page_range: str = "all"
    pages_per_sheet: int = 1
    page_order: str = "horizontal"
    color_mode: str = "black_white"
    duplex: str = "double"
    orientation: str = "portrait"
    scaling: str = "actual_size"
    custom_scale: float = 100
    margins: str = "default"
    backup_printer: str = ""
    customer_mobile: str = "Guest"
    amount: float = 2.0
    file_path: str = ""

class RazorpayOrderRequest(BaseModel):
    amount: float
    pages: Optional[int] = None
    copies: Optional[int] = None
    color_mode: Optional[str] = "black_white"
    pages_per_sheet: Optional[int] = 1
    order_id: Optional[str] = None
    customer_id: Optional[str] = "CUST_001"
    currency: Optional[str] = "INR"


@app.get("/api/orders")
def get_all_orders():
    orders_db[:] = load_orders()
    return {
        "status": "success",
        "total_orders": len(orders_db),
        "orders": orders_db
    }

@app.post("/print-order")
def create_print_order(order: PrintOrder):
    if not 1 <= order.copies <= 999:
        raise HTTPException(status_code=400, detail="Copies must be between 1 and 999")
    if order.pages < 1:
        raise HTTPException(status_code=400, detail="Pages must be at least 1")
    if order.color_mode not in ("black_white", "color", "micro_xerox"):
        raise HTTPException(status_code=400, detail="Unsupported color mode")
    if order.paper_size not in ("A3", "A4", "A5", "Letter", "Legal", "Executive", "Custom"):
        raise HTTPException(status_code=400, detail="Unsupported paper size")
    if order.orientation not in ("portrait", "landscape", "auto"):
        raise HTTPException(status_code=400, detail="Unsupported orientation")
    if order.duplex not in ("single", "double"):
        raise HTTPException(status_code=400, detail="Unsupported duplex mode")
    if order.page_order not in ("horizontal", "vertical"):
        raise HTTPException(status_code=400, detail="Unsupported page order")
    if order.scaling not in ("actual_size", "fit", "fill", "custom"):
        raise HTTPException(status_code=400, detail="Unsupported scaling mode")
    if not 10 <= order.custom_scale <= 500:
        raise HTTPException(status_code=400, detail="Custom scale must be between 10% and 500%")

    allowed_micro_sheet_counts = (2, 4, 6, 9, 16)
    if order.color_mode == "micro_xerox":
        if order.pages_per_sheet not in allowed_micro_sheet_counts:
            raise HTTPException(
                status_code=400,
                detail="Micro Xerox Pages Per Sheet must be 2, 4, 6, 9, or 16"
            )
    elif order.pages_per_sheet != 1:
        raise HTTPException(
            status_code=400,
            detail="Pages per sheet is only available for Micro Xerox"
        )

    physical_papers = (
        (order.pages + order.pages_per_sheet - 1)
        // order.pages_per_sheet
    ) * order.copies

    expected_amount = (
        physical_papers * 3
        if order.color_mode == "micro_xerox"
        else order.pages
        * order.copies
        * (6 if order.color_mode == "color" else 2)
    )

    if abs(order.amount - expected_amount) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Amount must be Rs.{expected_amount}"
        )

    order.pages_per_sheet = (
        order.pages_per_sheet
        if order.color_mode == "micro_xerox"
        else 1
    )
    order.page_order = (
        order.page_order
        if order.color_mode == "micro_xerox"
        else "horizontal"
    )

    order_id = f"PF-{uuid4().hex[:6].upper()}"
    new_order = {
        "order_id": order_id,
        "file_name": order.file_name,
        "copies": order.copies,
        "pages": order.pages,
        "file_size": order.file_size,
        "paper_size": order.paper_size,
        "page_range": order.page_range,
        "pages_per_sheet": order.pages_per_sheet,
        "page_order": order.page_order,
        "color_mode": order.color_mode,
        "duplex": order.duplex,
        "orientation": order.orientation,
        "scaling": order.scaling,
        "custom_scale": order.custom_scale,
        "margins": order.margins,
        "backup_printer": order.backup_printer,
        "customer_mobile": order.customer_mobile,
        "amount": order.amount,
        "file_path": order.file_path,
        "paid": False,
        "status": "Pending",
        "document_status": "UPLOADED",
        "print_error": None,
        "claimed_at": None,
        "printed_by_printer": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_order(new_order)
    print(f"[ORDER CREATED] Order {order_id} created for '{order.file_name}'")
    print(f"[ORDER SAVED] {order_id} persisted in durable storage")

    # Simulated WhatsApp / SMS Alert Trigger
    send_notification(
        order.customer_mobile,
        f"Hi! Your PrintFlow order {order_id} for '{order.file_name}' (Rs.{order.amount}) has been received successfully."
    )

    return {
        "status": "success",
        "message": "Print order created successfully",
        "order": new_order
    }

import time
from fastapi import Header

AGENT_STATE = {
    "last_seen": 0,
    "status": "OFFLINE",
    "printers": []
}

import threading

def schedule_secure_document_cleanup(order_id: str, delay_seconds: float = 2.5):
    def _cleanup_worker():
        time.sleep(delay_seconds)
        order = get_order(order_id)
        if order and order.get("file_path"):
            document_id = Path(order["file_path"]).name
            delete_document(document_id)
            order["file_path"] = ""
            order["document_status"] = "DELETED"
            order["deleted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_order(order)
            print(f"[PRIVACY CLEANUP SUCCESS] Document for Order {order_id} deleted after completion.")

    thread = threading.Thread(target=_cleanup_worker, daemon=True)
    thread.start()

def verify_agent_token(header_token: Optional[str]):
    expected_token = (os.environ.get("PRINT_AGENT_TOKEN") or "PF_AGENT_SECRET_TOKEN_2026").strip()
    if not header_token or header_token.strip() != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized PrintAgent Token")

def queue_order_for_printing(payload: dict):
    order_id = payload.get("print_order_id") or payload.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing print_order_id for verified payment")

    existing = get_order(order_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Print order {order_id} not found")
    try:
        queued_order = queue_paid_order(
            order_id,
            payload.get("razorpay_order_id", ""),
            payload.get("razorpay_payment_id", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not queued_order:
        raise HTTPException(status_code=404, detail=f"Print order {order_id} not found")
    print(f"[ORDER SAVED] Payment state persisted for {order_id}")
    print(f"[PRINT JOB QUEUED] Order {order_id} added to the durable agent queue")
    return queued_order

@app.post("/api/agent/poll")
def agent_poll_endpoint(req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    AGENT_STATE["last_seen"] = time.time()
    AGENT_STATE["status"] = "ONLINE"
    if "printers" in req:
        AGENT_STATE["printers"] = req["printers"]

    queued_jobs = [o for o in durable_list_orders() if o.get("status") == "PRINT_QUEUED"]
    print(f"[AGENT ONLINE] durable queue checked; jobs={len(queued_jobs)}")

    return {
        "status": "success",
        "agent_online": True,
        "jobs": queued_jobs
    }

@app.post("/api/agent/claim/{order_id}")
def agent_claim_endpoint(order_id: str, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    order = durable_claim_order(order_id)
    if not order:
        existing = get_order(order_id)
        if existing and existing.get("status") == "PRINTING":
            raise HTTPException(status_code=409, detail="Order already claimed by another agent worker")
        raise HTTPException(status_code=404, detail="Order not found or not queued")
    print(f"[JOB CLAIMED] {order_id} -> PRINTING")
    return {"status": "success", "message": f"Order {order_id} claimed successfully"}

@app.post("/api/agent/complete/{order_id}")
def agent_complete_endpoint(order_id: str, req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    status_val = req.get("status", "COMPLETED")
    if status_val not in ("COMPLETED", "FAILED"):
        raise HTTPException(status_code=400, detail="Completion status must be COMPLETED or FAILED")
    order = durable_complete_order(order_id, status_val, req.get("error", ""), req.get("printed_by_printer", ""))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if status_val == "COMPLETED":
        print(f"[PRINT COMPLETED] {order_id} on {req.get('printed_by_printer', 'configured printer')}")
        schedule_secure_document_cleanup(order_id, 2.5)
    else:
        print(f"[PRINT FAILED] {req.get('error', 'Unknown print error')}")
    return {"status": "success", "message": f"Order {order_id} state updated to {status_val}"}

@app.get("/api/orders/{order_id}/status")
@app.get("/api/orders/status/{order_id}")
def get_order_status_endpoint(order_id: str):
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "status": "success",
        "order_id": order["order_id"],
        "order_status": order.get("status", "Pending"),
        "document_status": order.get("document_status", "UPLOADED"),
        "deleted": order.get("document_status") == "DELETED",
        "print_error": order.get("print_error")
    }

@app.get("/api/agent/status")
def agent_status_endpoint():
    is_online = (time.time() - AGENT_STATE.get("last_seen", 0)) < 25
    from printer_manager import get_installed_printers, get_printer_config
    return {
        "status": "success",
        "agent_online": is_online,
        "agent_last_seen": AGENT_STATE.get("last_seen", 0),
        "discovered_printers": AGENT_STATE.get("printers") or get_installed_printers(),
        "config": get_printer_config()
    }

@app.post("/api/orders/{order_id}/retry")
def retry_order_endpoint(order_id: str):
    orders_db[:] = load_orders()
    for order in orders_db:
        if order["order_id"] == order_id:
            order["status"] = "PRINT_QUEUED"
            order["document_status"] = "UPLOADED"
            order["print_error"] = None
            order["retry_count"] = int(order.get("retry_count", 0) or 0) + 1
            save_orders(orders_db)
            return {"status": "success", "message": f"Order {order_id} reset to PRINT_QUEUED for retry"}
    raise HTTPException(status_code=404, detail="Order not found")

@app.post("/api/orders/{order_id}/cancel")
def cancel_order_endpoint(order_id: str):
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") in ("COMPLETED", "CANCELLED"):
        raise HTTPException(status_code=409, detail="Order cannot be cancelled in its current state")
    order["status"] = "CANCELLED"
    order["print_error"] = "Cancelled by administrator"
    save_order(order)
    return {"status": "success", "message": f"Order {order_id} cancelled"}

@app.post("/api/agent/test-print")
def test_print_endpoint(x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    test_id = f"TEST-{uuid4().hex[:6].upper()}"
    document_id = save_document("printflow-test.txt", "text/plain", b"PrintFlow durable storage printer test\r\n")
    test_order = {
        "order_id": test_id,
        "file_name": "printflow-test.txt",
        "file_path": f"/api/documents/{document_id}",
        "color_mode": "black_white",
        "copies": 1,
        "pages": 1,
        "duplex": "single",
        "orientation": "portrait",
        "customer_mobile": "+919999999999",
        "amount": 2.0,
        "paid": True,
        "status": "PRINT_QUEUED",
        "document_status": "UPLOADED",
        "print_error": None,
        "claimed_at": None,
        "printed_by_printer": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_order(test_order)
    print(f"[ORDER SAVED] Controlled test order {test_id} persisted in durable storage")
    return {"status": "success", "message": f"Test print order {test_id} queued", "order": test_order}

@app.post("/api/orders/{order_id}/complete")
def complete_order(order_id: str):
    orders_db[:] = load_orders()
    for order in orders_db:
        if order["order_id"] == order_id:
            order["status"] = "Completed"
            save_orders(orders_db)
            # Send Notification on completion
            send_notification(
                order["customer_mobile"],
                f"Your PrintFlow order {order_id} ('{order['file_name']}') is READY for pickup at the counter!"
            )
            return {
                "status": "success",
                "message": f"Order {order_id} marked as completed",
                "order": order
            }
    raise HTTPException(status_code=404, detail="Order not found")

@app.get("/api/printers")
def get_printers_endpoint():
    from printer_manager import get_installed_printers, get_printer_config
    return {
        "status": "success",
        "printers": get_installed_printers(),
        "config": get_printer_config()
    }

class PrinterConfigRequest(BaseModel):
    bw_printer: Optional[str] = ""
    color_printer: Optional[str] = ""

@app.post("/api/printers/config")
def save_printers_config_endpoint(req: PrinterConfigRequest):
    from printer_manager import save_printer_config, get_printer_config
    cfg = get_printer_config()
    if req.bw_printer is not None:
        cfg["bw_printer"] = req.bw_printer
    if req.color_printer is not None:
        cfg["color_printer"] = req.color_printer
    saved = save_printer_config(cfg)
    return {"status": "success", "config": saved}

@app.post("/api/orders/{order_id}/print")
def print_order_dispatch_endpoint(order_id: str):
    orders_db[:] = load_orders()
    for order in orders_db:
        if order["order_id"] == order_id:
            if not order.get("file_path"):
                raise HTTPException(status_code=400, detail="Order has no printable document")
            order["status"] = "PRINT_QUEUED"
            order["print_error"] = None
            save_order(order)
            return {
                "status": "success",
                "message": f"Print job for {order_id} queued for the local agent"
            }
    raise HTTPException(status_code=404, detail="Order not found")

def send_notification(mobile: str, message: str):
    try:
        print(f"[NOTIFICATION SENT TO {mobile}]: {message}")
    except Exception:
        pass

@app.post("/api/create-order")
@app.post("/create-razorpay-order")
@app.post("/api/create-razorpay-order")
def create_razorpay_order(request: RazorpayOrderRequest):
    # CRITICAL: Do NOT use fallback defaults. Fail clearly if credentials are missing.
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "").strip().strip('"').strip("'")
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip().strip('"').strip("'")

    # Validate credentials exist before proceeding
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=500,
            detail="RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are not configured in the server environment"
        )

    # Safe diagnostic logging (NEVER logs key_secret)
    is_live_key = key_id.startswith("rzp_live_")
    is_test_key = key_id.startswith("rzp_test_")
    mode_str = "LIVE" if is_live_key else ("TEST" if is_test_key else "UNKNOWN")
    masked_key_id = f"{key_id[:8]}...{key_id[-4:]}" if len(key_id) > 12 else "PRESENT"
    print(f"[RAZORPAY DIAGNOSTIC] KEY_ID: {masked_key_id}, Mode: {mode_str}, KEY_SECRET configured: true")

    # Handle amount input in either Rupees (e.g. 4.0) or Paise (e.g. 400)
    if request.amount >= 100:
        amount_in_paise = int(round(request.amount))
    else:
        amount_in_paise = int(round(request.amount * 100))

    if request.color_mode not in ("black_white", "color", "micro_xerox"):
        raise HTTPException(status_code=400, detail="Unsupported color mode")

    # Canonical pricing: color is Rs.6/page; B&W is Rs.2/page.
    if request.pages and request.copies and request.pages > 0 and request.copies > 0:
        if request.pages_per_sheet not in (1, 2, 4, 6, 9, 16):
            raise HTTPException(status_code=400, detail="Unsupported pages per sheet")
        physical_papers = ((request.pages + request.pages_per_sheet - 1) // request.pages_per_sheet) * request.copies
        expected_rupees = physical_papers * 3.0 if request.color_mode == "micro_xerox" else request.pages * request.copies * (6.0 if request.color_mode == "color" else 2.0)
        expected_paise = int(round(expected_rupees * 100))
        if amount_in_paise != expected_paise:
            raise HTTPException(status_code=400, detail=f"Amount must be Rs.{expected_rupees:g}")

    receipt_id = f"rcpt_{uuid4().hex[:10]}"

    if amount_in_paise < 100:
        raise HTTPException(status_code=400, detail="Minimum order amount must be at least 100 paise (INR 1.00)")

    try:
        import requests
        from requests.auth import HTTPBasicAuth
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
        if resp.status_code in (200, 201):
            razorpay_order = resp.json()
            if request.order_id:
                local_order = get_order(request.order_id)
                if local_order:
                    local_order["razorpay_order_id"] = razorpay_order["id"]
                    save_order(local_order)
            return {
                "status": "success",
                "key_id": key_id,
                "order_id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"],
                "mode": mode_str
            }
        else:
            print("Razorpay API Error Response:", resp.status_code, resp.text)
            raise HTTPException(status_code=resp.status_code, detail=f"Razorpay API Error: {resp.text}")
    except HTTPException:
        raise
    except Exception as err:
        print("Razorpay API order creation error:", err)
        raise HTTPException(status_code=500, detail=f"Razorpay order creation failed: {str(err)}")

@app.post("/api/verify-payment")
@app.post("/verify-razorpay-payment")
@app.post("/api/verify-razorpay-payment")
def verify_razorpay_payment(payload: dict):
    # CRITICAL: Do NOT use fallback defaults. Fail clearly if credential is missing.
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip().strip('"').strip("'")

    # Validate credential exists before proceeding
    if not key_secret:
        raise HTTPException(
            status_code=500,
            detail="RAZORPAY_KEY_SECRET is not configured in the server environment"
        )

    # Safe diagnostic logging (NEVER logs key_secret)
    print(f"[RAZORPAY VERIFY DIAGNOSTIC] KEY_SECRET configured: true")

    razorpay_order_id = payload.get("razorpay_order_id", "")
    razorpay_payment_id = payload.get("razorpay_payment_id", "")
    razorpay_signature = payload.get("razorpay_signature", "")

    if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
        raise HTTPException(status_code=400, detail="Missing required payment verification fields (order_id, payment_id, signature)")

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    generated_signature = hmac.new(
        key_secret.encode("utf-8"),
        msg,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature - payment verification failed")

    local_order = get_order(payload.get("print_order_id", ""))
    if not local_order:
        raise HTTPException(status_code=404, detail="Print order not found")
    if local_order.get("razorpay_order_id") and local_order["razorpay_order_id"] != razorpay_order_id:
        raise HTTPException(status_code=409, detail="Razorpay order does not match print order")
    pages = int(local_order.get("pages", 1))
    copies = int(local_order.get("copies", 1))
    pages_per_sheet = int(local_order.get("pages_per_sheet", 1) or 1)
    expected_amount = ((pages + pages_per_sheet - 1) // pages_per_sheet) * copies * 3 if local_order.get("color_mode") == "micro_xerox" else pages * copies * (6 if local_order.get("color_mode") == "color" else 2)
    if local_order.get("amount") is not None and abs(float(local_order["amount"]) - expected_amount) > 0.01:
        raise HTTPException(status_code=409, detail="Print order amount is inconsistent")

    print(f"[PAYMENT VERIFIED] Razorpay payment {razorpay_payment_id} verified for order {razorpay_order_id}")
    queued_order = queue_order_for_printing(payload)

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully. Job queued for PrintAgent.",
        "order_status": "PRINT_QUEUED",
        "payload": payload,
        "order": queued_order
    }

@app.post("/upload-pdf")
@app.post("/api/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file selected"
            )

        allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format '{file_ext}'. Supported formats: PDF, PNG, JPG, JPEG, WEBP, DOC, DOCX, TXT."
            )

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
        print("File upload error:", e)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/api/documents/{document_id}")
def download_document(document_id: str, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    from fastapi.responses import Response
    return Response(content=document["content"], media_type=document["mime_type"], headers={"Content-Disposition": f'attachment; filename="{document["file_name"]}"'})
