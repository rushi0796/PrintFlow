from fastapi import FastAPI
from main import RazorpayOrderRequest, create_razorpay_order

app = FastAPI()

@app.post("/")
@app.post("/api/create-razorpay-order")
def create_razorpay_order_endpoint(request: RazorpayOrderRequest):
    return create_razorpay_order(request)
