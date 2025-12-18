import os
import shutil
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

# Importação correta
from extractor_ocr import process_image_bill

app = FastAPI(title="API Leitura de Fatura por Foto (OCR)")

os.makedirs("temp_ocr", exist_ok=True)

@app.post("/ler-fatura-foto")
async def ler_fatura_foto(file: UploadFile = File(...)):
    filename = file.filename.lower()
    if not filename.endswith(('.jpg', '.jpeg', '.png')):
        raise HTTPException(status_code=400, detail="Apenas imagens (.jpg, .png)")

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1]
    temp_img_path = f"temp_ocr/{file_id}{ext}"

    try:
        with open(temp_img_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"📸 Foto recebida: {temp_img_path}")

        # --- CORREÇÃO AQUI ---
        # Usamos a função importada do extractor_ocr
        resultado = process_image_bill(temp_img_path)

        if isinstance(resultado, dict):
            resultado["_info_api"] = "Processado via OCR API"

        return JSONResponse(content=resultado)

    except Exception as e:
        print(f"❌ Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(temp_img_path):
            try:
                os.remove(temp_img_path)
            except:
                pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)