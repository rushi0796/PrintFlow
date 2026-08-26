from fastapi import FastAPI, File, UploadFile

from main import upload_pdf

app = FastAPI()


@app.post("/")
async def upload_pdf_endpoint(file: UploadFile = File(...)):
    return await upload_pdf(file)
