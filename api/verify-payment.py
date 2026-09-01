import os
import json
import hmac
import hashlib

def handler(request):
    try:
        body = json.loads(request.body) if hasattr(request, "body") and request.body else {}
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "Da1m2Uz4AwFSKEXyEQxLKG0b")
        
        razorpay_order_id = body.get("razorpay_order_id", "")
        razorpay_payment_id = body.get("razorpay_payment_id", "")
        razorpay_signature = body.get("razorpay_signature", "")

        if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"detail": "Missing required verification parameters"})
            }

        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        generated_signature = hmac.new(
            key_secret.encode("utf-8"),
            msg,
            hashlib.sha256
        ).hexdigest()

        if generated_signature != razorpay_signature:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"detail": "Invalid payment signature"})
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "success",
                "message": "Payment verified successfully",
                "payload": body
            })
        }
    except Exception as err:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"detail": str(err)})
        }
