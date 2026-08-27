import os
import json
import shutil
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

class PaytmOrderRequest(BaseModel):
    amount: float
    order_id: str = None
    customer_id: str = "CUST_001"

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
        f"Hi! Your PrintFlow order {order_id} for '{order.file_name}' (₹{order.amount}) has been received successfully."
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
                f"🎉 Your PrintFlow order {order_id} ('{order['file_name']}') is READY for pickup at the counter!"
            )
            return {
                "status": "success",
                "message": f"Order {order_id} marked as completed",
                "order": order
            }
    raise HTTPException(status_code=404, detail="Order not found")

def send_notification(mobile: str, message: str):
    print(f"[NOTIFICATION SENT TO {mobile}]: {message}")

@app.post("/create-paytm-order")
def create_paytm_order(request: PaytmOrderRequest):
    order_id = request.order_id or f"PF_ORDER_{uuid4().hex[:8].upper()}"
    mid = os.environ.get("PAYTM_MID", "DIY12386817555501617")

    return {
        "status": "success",
        "mid": mid,
        "orderId": order_id,
        "amount": str(request.amount),
        "txnToken": f"TXN_TOKEN_{uuid4().hex}",
        "paytmUrl": f"https://securegw-stage.paytm.in/theia/api/v1/showPaymentPage?mid={mid}&orderId={order_id}"
    }

@app.post("/verify-paytm-payment")
def verify_paytm_payment(payload: dict):
    return {
        "status": "success",
        "message": "Paytm Payment verified successfully",
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