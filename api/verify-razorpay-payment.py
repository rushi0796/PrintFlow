import os
import hmac
import hashlib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/")
@app.post("/api/verify-payment")
@app.post("/verify-razorpay-payment")
@app.post("/api/verify-razorpay-payment")
def verify_payment(payload: dict):
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
        raise HTTPException(status_code=400, detail="Missing required payment verification fields")

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    generated_signature = hmac.new(
        key_secret.encode("utf-8"),
        msg,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature")

    from storage import get_order
    local_order = get_order(payload.get("print_order_id", ""))
    if not local_order:
        raise HTTPException(status_code=404, detail="Print order not found")
    if local_order.get("razorpay_order_id") and local_order["razorpay_order_id"] != razorpay_order_id:
        raise HTTPException(status_code=409, detail="Razorpay order does not match print order")
    expected_amount = int(local_order.get("pages", 1)) * int(local_order.get("copies", 1)) * (6 if local_order.get("color_mode") == "color" else 2)
    if abs(float(local_order.get("amount", expected_amount)) - expected_amount) > 0.01:
        raise HTTPException(status_code=409, detail="Print order amount is inconsistent")

    from main import queue_order_for_printing
    print(f"[PAYMENT VERIFIED] Razorpay payment {razorpay_payment_id} verified for order {razorpay_order_id}")
    queued_order = queue_order_for_printing(payload)

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully. Job queued for PrintAgent.",
        "order_status": "PRINT_QUEUED",
        "payload": payload,
        "order": queued_order
    }
