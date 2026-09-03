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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

UPLOAD_DIR = (
    Path("/tmp/printflow-uploads")
    if os.environ.get("VERCEL")
    else BASE_DIR / "uploads"
)
UPLOAD_DIR.mkdir(exist_ok=True)
ORDER_FILE = (
    Path("/tmp/printflow-orders.json")
    if os.environ.get("VERCEL")
    else BASE_DIR / "orders" / "orders.json"
)

# Serve uploaded PDF files statically for download & printing in Admin Dashboard
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# In-memory orders database for Admin Dashboard
def load_orders():
    try:
        if ORDER_FILE.exists():
            return json.loads(ORDER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_orders(orders):
    ORDER_FILE.parent.mkdir(exist_ok=True)
    ORDER_FILE.write_text(json.dumps(orders), encoding="utf-8")


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

class PrintOrder(BaseModel):
    file_name: str
    copies: int = 1
    pages: int = 1
    color_mode: str = "black_white"
    duplex: str = "double"
    orientation: str = "portrait"
    customer_mobile: str = "Guest"
    amount: float = 2.0
    file_path: str = ""

class RazorpayOrderRequest(BaseModel):
    amount: float
    pages: Optional[int] = None
    copies: Optional[int] = None
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
    orders_db[:] = load_orders()
    order_id = f"PF-{uuid4().hex[:6].upper()}"
    new_order = {
        "order_id": order_id,
        "file_name": order.file_name,
        "copies": order.copies,
        "pages": order.pages,
        "color_mode": order.color_mode,
        "duplex": order.duplex,
        "orientation": order.orientation,
        "customer_mobile": order.customer_mobile,
        "amount": order.amount,
        "file_path": order.file_path,
        "status": "Pending",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    orders_db.insert(0, new_order)
    save_orders(orders_db)

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
        orders_db[:] = load_orders()
        for order in orders_db:
            if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
                order["document_status"] = "DELETING"
                file_rel_path = order.get("file_path", "")
                if file_rel_path:
                    clean_name = Path(file_rel_path).name
                    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
                    file_ext = Path(clean_name).suffix.lower()
                    if file_ext in allowed_exts:
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
                save_orders(orders_db)
                break

    thread = threading.Thread(target=_cleanup_worker, daemon=True)
    thread.start()

def verify_agent_token(header_token: Optional[str]):
    expected_token = (os.environ.get("PRINT_AGENT_TOKEN") or "PF_AGENT_SECRET_TOKEN_2026").strip()
    if not header_token or header_token.strip() != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized PrintAgent Token")

def queue_order_for_printing(payload: dict):
    orders_db[:] = load_orders()
    order_id = payload.get("razorpay_order_id") or payload.get("order_id")
    if not order_id:
        return
    for order in orders_db:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            order["status"] = "PRINT_QUEUED"
            order["document_status"] = "UPLOADED"
            order["paid"] = True
            save_orders(orders_db)
            return
    new_queued = {
        "order_id": order_id,
        "file_name": payload.get("file_name", "document.pdf"),
        "file_path": payload.get("file_path", "/uploads/test.pdf"),
        "color_mode": payload.get("color_mode", "black_white"),
        "copies": int(payload.get("copies", 1)),
        "orientation": payload.get("orientation", "portrait"),
        "customer_mobile": payload.get("customer_mobile", "Guest"),
        "amount": payload.get("amount", 2.0),
        "status": "PRINT_QUEUED",
        "document_status": "UPLOADED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    orders_db.insert(0, new_queued)
    save_orders(orders_db)

@app.post("/api/agent/poll")
def agent_poll_endpoint(req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    AGENT_STATE["last_seen"] = time.time()
    AGENT_STATE["status"] = "ONLINE"
    if "printers" in req:
        AGENT_STATE["printers"] = req["printers"]

    orders_db[:] = load_orders()
    queued_jobs = [o for o in orders_db if o.get("status") in ("PRINT_QUEUED", "Pending")]

    return {
        "status": "success",
        "agent_online": True,
        "jobs": queued_jobs
    }

@app.post("/api/agent/claim/{order_id}")
def agent_claim_endpoint(order_id: str, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    orders_db[:] = load_orders()
    for order in orders_db:
        if order["order_id"] == order_id:
            if order.get("status") == "PRINTING":
                raise HTTPException(status_code=409, detail="Order already claimed by another agent worker")
            order["status"] = "PRINTING"
            order["document_status"] = "PRINTING"
            order["claimed_at"] = time.time()
            save_orders(orders_db)
            return {"status": "success", "message": f"Order {order_id} claimed successfully"}
    raise HTTPException(status_code=404, detail="Order not found")

@app.post("/api/agent/complete/{order_id}")
def agent_complete_endpoint(order_id: str, req: dict, x_print_agent_token: Optional[str] = Header(None)):
    verify_agent_token(x_print_agent_token)
    orders_db[:] = load_orders()
    status_val = req.get("status", "COMPLETED")
    for order in orders_db:
        if order["order_id"] == order_id:
            order["status"] = status_val
            if status_val in ("COMPLETED", "Completed"):
                order["document_status"] = "PRINTED"
                save_orders(orders_db)
                schedule_secure_document_cleanup(order_id, 2.5)
            elif status_val == "FAILED":
                order["document_status"] = "UPLOADED" # Retain file for retry
                if "error" in req:
                    order["print_error"] = req["error"]
                save_orders(orders_db)
            if "printed_by_printer" in req:
                order["printed_by_printer"] = req["printed_by_printer"]
            return {"status": "success", "message": f"Order {order_id} state updated to {status_val}"}
    raise HTTPException(status_code=404, detail="Order not found")

@app.get("/api/orders/{order_id}/status")
@app.get("/api/orders/status/{order_id}")
def get_order_status_endpoint(order_id: str):
    orders_db[:] = load_orders()
    for order in orders_db:
        if order.get("order_id") == order_id or order.get("razorpay_order_id") == order_id:
            return {
                "status": "success",
                "order_id": order_id,
                "order_status": order.get("status", "COMPLETED"),
                "document_status": order.get("document_status", "DELETED"),
                "deleted": order.get("document_status") == "DELETED" or not bool(order.get("file_path"))
            }
    return {
        "status": "success",
        "order_id": order_id,
        "order_status": "COMPLETED",
        "document_status": "DELETED",
        "deleted": True
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
            save_orders(orders_db)
            return {"status": "success", "message": f"Order {order_id} reset to PRINT_QUEUED for retry"}
    raise HTTPException(status_code=404, detail="Order not found")

@app.post("/api/agent/test-print")
def test_print_endpoint():
    orders_db[:] = load_orders()
    test_id = f"TEST-{uuid4().hex[:6].upper()}"
    test_order = {
        "order_id": test_id,
        "file_name": "test.pdf",
        "file_path": "/uploads/test.pdf",
        "color_mode": "black_white",
        "copies": 1,
        "pages": 1,
        "duplex": "single",
        "orientation": "portrait",
        "customer_mobile": "+919999999999",
        "amount": 2.0,
        "status": "PRINT_QUEUED",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    orders_db.insert(0, test_order)
    save_orders(orders_db)
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
            from print_dispatcher import dispatch_print_job
            print_res = dispatch_print_job(order)
            order["status"] = "Printing"
            save_orders(orders_db)
            return {
                "status": "success",
                "message": f"Print job for {order_id} dispatched to printer",
                "dispatch": print_res
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
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "rzp_live_TXZidkYDGHaDOh").strip().strip('"').strip("'")
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "FKi1Qw6tdcKvY9N2pmX2IjCf").strip().strip('"').strip("'")

    # Safe diagnostic logging (NEVER logs key_secret)
    has_key_id = bool(key_id)
    has_key_secret = bool(key_secret)
    is_live_key = key_id.startswith("rzp_live_")
    is_test_key = key_id.startswith("rzp_test_")
    mode_str = "LIVE" if is_live_key else ("TEST" if is_test_key else "UNKNOWN")
    masked_key_id = f"{key_id[:8]}...{key_id[-4:]}" if len(key_id) > 12 else ("PRESENT" if key_id else "MISSING")
    print(f"[RAZORPAY DIAGNOSTIC] KEY_ID present: {has_key_id}, Mode: {mode_str}, Starts with rzp_live_: {is_live_key}, Key ID: {masked_key_id}, KEY_SECRET present: {has_key_secret}")

    # Handle amount input in either Rupees (e.g. 4.0) or Paise (e.g. 400)
    if request.amount >= 100:
        amount_in_paise = int(round(request.amount))
    else:
        amount_in_paise = int(round(request.amount * 100))

    # Backend independent amount validation formula: Page Count × Copies × ₹2
    if request.pages and request.copies and request.pages > 0 and request.copies > 0:
        expected_rupees = request.pages * request.copies * 2.0
        expected_paise = int(round(expected_rupees * 100))
        if amount_in_paise < expected_paise:
            print(f"[PRICING VALIDATION] Correcting amount from {amount_in_paise}p to {expected_paise}p ({request.pages} pages x {request.copies} copies x Rs.2)")
            amount_in_paise = expected_paise

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
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "FKi1Qw6tdcKvY9N2pmX2IjCf").strip().strip('"').strip("'")
    has_key_secret = bool(key_secret)
    print(f"[RAZORPAY VERIFY DIAGNOSTIC] KEY_SECRET present: {has_key_secret}")

    if not key_secret:
        raise HTTPException(status_code=400, detail="RAZORPAY_KEY_SECRET not configured in server environment variables.")

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

    # Queue print job for local Windows PrintAgent
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
        saved_filename = f"{uuid4().hex[:8]}_{original_name}"
        file_path = UPLOAD_DIR / saved_filename

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

        returned_path = f"/uploads/{saved_filename}"

        return {
            "status": "success",
            "message": "File uploaded successfully",
            "file_name": file.filename,
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
