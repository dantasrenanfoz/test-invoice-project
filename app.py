from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import uuid
import shutil
import os

from extractor import process_copel_bill

app = FastAPI(title="API Copel - Leitura de Fatura")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

@app.post("/ler-fatura-pdf")
async def ler_fatura_pdf(pdf: UploadFile = File(...)):
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo precisa ser PDF")

    temp_path = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(pdf.file, f)

        resultado = process_copel_bill(temp_path)

        return JSONResponse(content=resultado)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_path.exists():
            temp_path.unlink()
