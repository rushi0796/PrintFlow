from fastapi import FastAPI
from main import verify_razorpay_payment

app = FastAPI()

@app.post("/")
@app.post("/api/verify-razorpay-payment")
def verify_razorpay_payment_endpoint(payload: dict):
    return verify_razorpay_payment(payload)
