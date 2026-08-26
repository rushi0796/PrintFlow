from fastapi import FastAPI

from main import health

app = FastAPI()


@app.get("/")
@app.get("/api/health")
def health_endpoint():
    return health()
