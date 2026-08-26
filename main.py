import os
import shutil
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = (
    Path("/tmp/printflow-uploads")
    if os.environ.get("VERCEL")
    else BASE_DIR / "uploads"
)
UPLOAD_DIR.mkdir(exist_ok=True)

@app.get("/")
def home():
    return {
        "app": "PrintFlow",
        "status": "Backend running successfully"
    }

@app.get("/health")
def health():
    return {
        "status": "online"
    }

class PrintOrder(BaseModel):
    file_name: str
    copies: int
    color_mode: str
    duplex: str
    orientation: str

@app.post("/print-order")
def create_print_order(order: PrintOrder):
    return {
        "status": "received",
        "message": "Print order received successfully",
        "order": order
    }

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file selected"
            )

        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
            )

        original_name = Path(file.filename).name
        file_path = UPLOAD_DIR / f"{uuid4().hex}_{original_name}"

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

        return {
            "status": "success",
            "message": "PDF uploaded successfully",
            "file_name": file.filename,
            "file_path": str(file_path.relative_to(BASE_DIR))
        }

    except HTTPException:
        raise

    except Exception as e:
        print("PDF upload error:", e)

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )