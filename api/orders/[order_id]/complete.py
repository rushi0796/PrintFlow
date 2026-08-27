from fastapi import FastAPI

from main import complete_order

app = FastAPI()


@app.post("/")
@app.post("/api/orders/{order_id}/complete")
def complete_order_endpoint(order_id: str):
    return complete_order(order_id)