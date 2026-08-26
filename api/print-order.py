from fastapi import FastAPI

from main import PrintOrder, create_print_order

app = FastAPI()


@app.post("/")
@app.post("/api/print-order")
def print_order_endpoint(order: PrintOrder):
    return create_print_order(order)
