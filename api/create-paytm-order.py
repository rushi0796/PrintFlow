from fastapi import FastAPI

from main import PaytmOrderRequest, create_paytm_order

app = FastAPI()


@app.post("/")
@app.post("/api/create-paytm-order")
def create_paytm_order_endpoint(request: PaytmOrderRequest):
    return create_paytm_order(request)