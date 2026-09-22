from fastapi import FastAPI, File, UploadFile, Form
from typing import Optional
from main import upload_chunk_endpoint

app = FastAPI()

@app.post("/")
@app.post("/upload-chunk")
@app.post("/api/upload-chunk")
async def upload_chunk_api(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    file_name: str = Form(...),
    file_size: Optional[int] = Form(None),
    chunk: UploadFile = File(...)
):
    return await upload_chunk_endpoint(upload_id, chunk_index, total_chunks, file_name, file_size, chunk)
