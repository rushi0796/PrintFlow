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
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip().strip('"').strip("'")

    # Safe diagnostic logging (NEVER logs key_secret)
    has_key_secret = bool(key_secret)
    print(f"[RAZORPAY VERIFY DIAGNOSTIC] KEY_SECRET present: {has_key_secret}")

    if not key_secret:
        raise HTTPException(
            status_code=400,
            detail="RAZORPAY_KEY_SECRET not configured in server environment variables."
        )

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

    return {
        "status": "success",
        "message": "Razorpay Payment verified successfully",
        "payload": payload
    }
