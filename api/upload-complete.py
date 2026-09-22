from fastapi import FastAPI, Form
from typing import Optional
from main import upload_complete_endpoint

app = FastAPI()

@app.post("/")
@app.post("/upload-complete")
@app.post("/api/upload-complete")
async def upload_complete_api(
    upload_id: str = Form(...),
    file_name: str = Form(...),
    total_chunks: int = Form(...),
    mime_type: Optional[str] = Form(None)
):
    return await upload_complete_endpoint(upload_id, file_name, total_chunks, mime_type)
