import os
import json
import time
from typing import Optional
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
    pages: Optional[int] = None
    copies: Optional[int] = None
    color_mode: str = "black_white"
    pages_per_sheet: int = 1
    currency: str = "INR"
    order_id: str = None

@app.post("/")
@app.post("/api/create-order")
@app.post("/create-razorpay-order")
@app.post("/api/create-razorpay-order")
def create_order(req: OrderReq):
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
    print(f"[RAZORPAY DIAGNOSTIC] KEY_ID: {masked_key_id}, Mode: {mode_str}, KEY_SECRET configured: {bool(key_secret)}")

    # Handle amount input in either Rupees (e.g. 4.0) or Paise (e.g. 400)
    if req.amount >= 100:
        amount_in_paise = int(round(req.amount))
    else:
        amount_in_paise = int(round(req.amount * 100))

    if req.color_mode not in ("black_white", "color", "micro_xerox"):
        raise HTTPException(status_code=400, detail="Unsupported color mode")

    if req.pages and req.copies and req.pages > 0 and req.copies > 0:
        if req.color_mode == "micro_xerox":
            if req.pages_per_sheet not in (2, 4, 6, 9, 16):
                raise HTTPException(
                    status_code=400,
                    detail="Micro Xerox Pages Per Sheet must be 2, 4, 6, 9, or 16"
                )
            sheet_count = req.pages_per_sheet
        else:
            if req.pages_per_sheet != 1:
                raise HTTPException(
                    status_code=400,
                    detail="Pages per sheet is only available for Micro Xerox"
                )
            sheet_count = 1

        physical_papers = (
            (req.pages + sheet_count - 1) // sheet_count
        ) * req.copies

        expected_rupees = (
            physical_papers * 3.0
            if req.color_mode == "micro_xerox"
            else req.pages
            * req.copies
            * (6.0 if req.color_mode == "color" else 2.0)
        )
        expected_paise = int(round(expected_rupees * 100))

        if amount_in_paise != expected_paise:
            raise HTTPException(
                status_code=400,
                detail=f"Amount must be Rs.{expected_rupees:g}"
            )

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
