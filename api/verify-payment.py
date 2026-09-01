from fastapi import FastAPI
from main import verify_razorpay_payment

app = FastAPI()

@app.post("/")
@app.post("/api/verify-payment")
def verify_payment_endpoint(payload: dict):
    return verify_razorpay_payment(payload)
