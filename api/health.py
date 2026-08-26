from fastapi import FastAPI

from main import health

app = FastAPI()


@app.get("/")
def health_endpoint():
    return health()
