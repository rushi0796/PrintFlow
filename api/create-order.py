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

@app.post("/")
@app.post("/api/create-order")
@app.post("/create-razorpay-order")
def create_order(req: OrderReq):
    key_id = "rzp_test_TWe9HlNAQDftjb"
    key_secret = "Da1m2Uz4AwFSKEXyEQxLKG0b"

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

        last_resp_text = ""
        for attempt in range(3):
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
                    "currency": rzp_order["currency"]
                }
            else:
                last_resp_text = resp.text
                rzp_payload["amount"] += 100
                rzp_payload["receipt"] = f"rcpt_{uuid4().hex[:12]}"
                time.sleep(0.3)

        raise HTTPException(status_code=500, detail=f"Razorpay API Error: {last_resp_text}")
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Razorpay order creation error: {str(err)}")
