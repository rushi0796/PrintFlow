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
    except Exception:
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
        if duplex == "double":
            return float(pages * copies * CANONICAL_PRICING["bw_double"])
        else:
            return float(pages * copies * CANONICAL_PRICING["bw_single"])

class PrintOrder(BaseModel):
    file_name: str
    copies: int = 1
    pages: int = 1
    color_mode: str = "black_white"
    duplex: str = "single"
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
    print_mode: Optional[str] = "standard"
    pages_per_sheet: Optional[int] = 1
    order_id: Optional[str] = None
    customer_id: Optional[str] = "CUST_001"
    currency: Optional[str] = "INR"

@app.get("/api/orders")
def get_all_orders():
    orders = load_orders()
    return {
        "status": "success",
        "total_orders": len(orders),
        "orders": orders
    }

@app.post("/print-order")
def create_print_order(order: PrintOrder):
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    calculated_amount = calculate_order_amount(
        order.pages, order.copies, order.color_mode, order.duplex, order.print_mode, order.pages_per_sheet
    )
    new_order = {
        "order_id": order_id,
        "file_name": order.file_name,
        "copies": order.copies,
        "pages": order.pages,
        "color_mode": order.color_mode,
        "duplex": order.duplex,
        "paper_size": order.paper_size,
        "orientation": order.orientation,
        "scale_mode": order.scale_mode,
        "margins": order.margins,
        "print_mode": order.print_mode,
        "pages_per_sheet": order.pages_per_sheet,
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
                    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
                    if Path(clean_name).suffix.lower() in allowed_exts:
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
    order_id = payload.get("razorpay_order_id") or payload.get("order_id")
    if not order_id:
        return
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            order["status"] = "PRINT_QUEUED"
            order["document_status"] = "UPLOADED"
            order["paid"] = True
            save_order(order)
            return
    new_queued = {
        "order_id": order_id,
        "file_name": payload.get("file_name", "document.pdf"),
        "file_path": payload.get("file_path", "/uploads/test.pdf"),
        "color_mode": payload.get("color_mode", "black_white"),
        "copies": int(payload.get("copies", 1)),
        "pages": int(payload.get("pages", 1)),
        "duplex": payload.get("duplex", "single"),
        "paper_size": payload.get("paper_size", "a4"),
        "orientation": payload.get("orientation", "portrait"),
        "scale_mode": payload.get("scale_mode", "fit"),
        "margins": payload.get("margins", "normal"),
        "print_mode": payload.get("print_mode", "standard"),
        "pages_per_sheet": int(payload.get("pages_per_sheet", 1)),
        "page_order": payload.get("page_order", "horizontal"),
        "customer_mobile": payload.get("customer_mobile", "Guest"),
        "amount": float(payload.get("amount", 2.0)),
        "paid": True,
        "status": "PRINT_QUEUED",
        "document_status": "UPLOADED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_order(new_queued)

@app.post("/api/agent/poll")
def agent_poll_endpoint(req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    AGENT_STATE["last_seen"] = time.time()
    AGENT_STATE["status"] = "ONLINE"
    if "printers" in req:
        AGENT_STATE["printers"] = req["printers"]

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
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            if order.get("status") == "PRINTING":
                raise HTTPException(status_code=409, detail=f"Order {order_id} is already claimed and currently PRINTING.")
            order["status"] = "PRINTING"
            order["document_status"] = "PRINTING"
            order["claimed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_order(order)
            return {
                "status": "success",
                "message": f"Order {order_id} claimed successfully",
                "order": order
            }
    raise HTTPException(status_code=404, detail="Order not found")

@app.post("/api/agent/complete/{order_id}")
def agent_complete_job_endpoint(order_id: str, req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            new_status = req.get("status", "COMPLETED")
            order["status"] = new_status
            if new_status == "COMPLETED":
                order["document_status"] = "PRINTED"
                order["printed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                order["printed_by_printer"] = req.get("printed_by_printer", "Windows Printer")
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
    raise HTTPException(status_code=404, detail="Order not found")

@app.get("/api/orders/{order_id}/status")
def get_order_status_endpoint(order_id: str):
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            return {
                "status": "success",
                "order_id": order_id,
                "order_status": order.get("status", "PRINT_QUEUED"),
                "document_status": order.get("document_status", "UPLOADED"),
                "deleted": order.get("document_status") == "DELETED",
                "order": order
            }
    return {
        "status": "success",
        "order_id": order_id,
        "order_status": "PRINT_QUEUED",
        "document_status": "DELETED",
        "deleted": True
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
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "rzp_live_TXZidkYDGHaDOh").strip().strip('"').strip("'")
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "FKi1Qw6tdcKvY9N2pmX2IjCf").strip().strip('"').strip("'")

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
        if resp.status_code in (200, 201):
            razorpay_order = resp.json()
            return {
                "status": "success",
                "key_id": key_id,
                "order_id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"],
                "mode": mode_str
            }
        else:
            mock_order_id = f"order_{uuid4().hex[:14]}"
            return {
                "status": "success",
                "key_id": key_id,
                "order_id": mock_order_id,
                "amount": amount_in_paise,
                "currency": request.currency or "INR",
                "mode": mode_str
            }
    except Exception:
        mock_order_id = f"order_{uuid4().hex[:14]}"
        return {
            "status": "success",
            "key_id": key_id,
            "order_id": mock_order_id,
            "amount": amount_in_paise,
            "currency": request.currency or "INR",
            "mode": mode_str
        }

@app.post("/api/verify-payment")
@app.post("/verify-razorpay-payment")
@app.post("/api/verify-razorpay-payment")
def verify_razorpay_payment(payload: dict):
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "FKi1Qw6tdcKvY9N2pmX2IjCf").strip().strip('"').strip("'")
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

    try:
        queue_order_for_printing(payload)
    except Exception as q_err:
        print("[QUEUE PRINT JOB EXCEPTION]:", q_err)

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully. Job queued for PrintAgent.",
        "order_status": "PRINT_QUEUED",
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
        saved_filename = f"{uuid4().hex[:8]}_{original_name}"
        file_path = UPLOAD_DIR / saved_filename

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        returned_path = f"/uploads/{saved_filename}"

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

@app.post("/api/orders/{order_id}/retry")
def retry_order_endpoint(order_id: str):
    orders = load_orders()
    for order in orders:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            order["status"] = "PRINT_QUEUED"
            save_order(order)
            return {
                "status": "success",
                "message": f"Order {order_id} reset to PRINT_QUEUED for retry",
                "order_status": "PRINT_QUEUED",
                "order": order
            }
    retry_queued = {
        "order_id": order_id,
        "file_name": "document.pdf",
        "file_path": "/uploads/test.pdf",
        "color_mode": "black_white",
        "copies": 1,
        "pages": 1,
        "duplex": "single",
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
