from fastapi import FastAPI, UploadFile, File, Form
from pathlib import Path
import shutil
import uuid

from extractor import extract_pdf, extract_fields

app = FastAPI()

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

@app.post("/extract-fatura")
async def extract_fatura(
    pdf: UploadFile = File(...),
    senha: str = Form(...)
):
    temp_pdf = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    with open(temp_pdf, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    try:
        page, words, text = extract_pdf(temp_pdf, senha)
        return extract_fields(page, words, text)
    finally:
        temp_pdf.unlink(missing_ok=True)
