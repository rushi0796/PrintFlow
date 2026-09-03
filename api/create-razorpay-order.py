import os
import json
import time
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from requests.auth import HTTPBasicAuth

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class OrderReq(BaseModel):
    amount: float
    currency: str = "INR"
    order_id: str = None

@app.post("/")
@app.post("/api/create-order")
@app.post("/create-razorpay-order")
@app.post("/api/create-razorpay-order")
def create_order(req: OrderReq):
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
    if req.amount >= 100:
        amount_in_paise = int(round(req.amount))
    else:
        amount_in_paise = int(round(req.amount * 100))

    if amount_in_paise < 100:
        raise HTTPException(status_code=400, detail="Minimum order amount must be at least 100 paise (INR 1.00)")

    receipt_id = f"rcpt_{uuid4().hex[:12]}"

    try:
        rzp_url = "https://api.razorpay.com/v1/orders"
        rzp_payload = {
            "amount": amount_in_paise,
            "currency": req.currency or "INR",
            "receipt": receipt_id,
            "payment_capture": 1
        }
        headers = {
            "User-Agent": "Razorpay/v1 PythonSDK/1.4.0",
            "Accept": "application/json"
        }

        resp = requests.post(
            rzp_url,
            auth=HTTPBasicAuth(key_id, key_secret),
            headers=headers,
            json=rzp_payload,
            timeout=15
        )
        if resp.status_code in (200, 201):
            rzp_order = resp.json()
            return {
                "status": "success",
                "key_id": key_id,
                "order_id": rzp_order["id"],
                "amount": rzp_order["amount"],
                "currency": rzp_order["currency"],
                "mode": mode_str
            }
        else:
            raise HTTPException(status_code=resp.status_code, detail=f"Razorpay API Error: {resp.text}")
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Razorpay order creation error: {str(err)}")
