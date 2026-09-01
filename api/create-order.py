import os
import json
import hmac
import hashlib
from uuid import uuid4

def handler(request):
    try:
        body = json.loads(request.body) if hasattr(request, "body") and request.body else {}
        amount = float(body.get("amount", 2.0))
        currency = body.get("currency", "INR")
        receipt = body.get("order_id") or f"order_{uuid4().hex[:14]}"
        
        amount_in_paise = int(round(amount * 100))
        if amount_in_paise < 100:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"detail": "Minimum amount is 100 paise"})
            }

        key_id = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_TWe9HlNAQDftjb")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "Da1m2Uz4AwFSKEXyEQxLKG0b")

        if key_secret and key_id:
            try:
                import razorpay
                client = razorpay.Client(auth=(key_id, key_secret))
                rzp_order = client.order.create({
                    "amount": amount_in_paise,
                    "currency": currency,
                    "receipt": receipt,
                    "payment_capture": 1
                })
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({
                        "status": "success",
                        "key_id": key_id,
                        "order_id": rzp_order["id"],
                        "amount": rzp_order["amount"],
                        "currency": rzp_order["currency"]
                    })
                }
            except Exception as e:
                pass

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "success",
                "key_id": key_id,
                "order_id": receipt,
                "amount": amount_in_paise,
                "currency": currency
            })
        }
    except Exception as err:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"detail": str(err)})
        }
