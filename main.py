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
    order_id: Optional[str] = None
    customer_id: Optional[str] = "CUST_001"
    currency: Optional[str] = "INR"

class ReviewerLoginRequest(BaseModel):
    mobile: Optional[str] = "9999999999"
    access_key: str

@app.post("/api/reviewer-login")
@app.post("/reviewer-login")
def reviewer_login(req: ReviewerLoginRequest):
    expected_key = os.environ.get("REVIEWER_ACCESS_KEY", "Reviewer@2026")
    if req.access_key.strip() != expected_key:
        raise HTTPException(status_code=401, detail="Invalid Reviewer Access Key. Please enter valid reviewer credentials.")
    
    formatted_mobile = (req.mobile or "9999999999").strip()
    if not formatted_mobile.startswith("+91"):
        formatted_mobile = f"+91{formatted_mobile.lstrip('+91')}"
    
    return {
        "status": "success",
        "message": "Reviewer authentication successful",
        "mobile": formatted_mobile,
        "is_reviewer": True
    }

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

def send_notification(mobile: str, message: str):
    try:
        print(f"[NOTIFICATION SENT TO {mobile}]: {message}")
    except Exception:
        pass

@app.post("/api/create-order")
@app.post("/create-razorpay-order")
@app.post("/api/create-razorpay-order")
def create_razorpay_order(request: RazorpayOrderRequest):
    key_id = (os.environ.get("RAZORPAY_KEY_ID") or "rzp_test_TWe9HlNAQDftjb").strip().strip('"').strip("'")
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "Da1m2Uz4AwFSKEXyEQxLKG0b").strip().strip('"').strip("'")

    if not key_id or "TWe9HlNAQDftjb" not in key_id:
        key_id = "rzp_test_TWe9HlNAQDftjb"

    if not key_secret or len(key_secret) < 20:
        key_secret = "Da1m2Uz4AwFSKEXyEQxLKG0b"

    # Handle amount input in either Rupees (e.g. 2.0) or Paise (e.g. 200)
    if request.amount >= 100:
        amount_in_paise = int(round(request.amount))
    else:
        amount_in_paise = int(round(request.amount * 100))

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
        resp = requests.post(rzp_url, auth=HTTPBasicAuth(key_id, key_secret), json=rzp_payload, timeout=10)
        if resp.status_code in (200, 201):
            razorpay_order = resp.json()
            return {
                "status": "success",
                "key_id": key_id,
                "order_id": razorpay_order["id"],
                "amount": razorpay_order["amount"],
                "currency": razorpay_order["currency"]
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
    key_secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "Da1m2Uz4AwFSKEXyEQxLKG0b").strip().strip('"').strip("'")
    if not key_secret or len(key_secret) < 20:
        key_secret = "Da1m2Uz4AwFSKEXyEQxLKG0b"
        raise HTTPException(
            status_code=500,
            detail="RAZORPAY_KEY_SECRET not configured in server environment variables."
        )

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

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully",
        "payload": payload
    }

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file selected"
            )

        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
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
            "message": "PDF uploaded successfully",
            "file_name": file.filename,
            "file_path": returned_path
        }

    except HTTPException:
        raise

    except Exception as e:
        print("PDF upload error:", e)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )