from fastapi import FastAPI

from main import get_all_orders

app = FastAPI()


@app.get("/")
@app.get("/api/orders")
def orders_endpoint():
    return get_all_orders()