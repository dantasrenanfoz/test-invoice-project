from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from pathlib import Path
import shutil
import uuid
import os

# =====================================================
# IMPORTAÇÕES DOS EXTRATORES
# =====================================================
from extractor import process_copel_bill  # Lê PDF Digital
from extractor_ocr import process_image_bill  # Lê Foto (OCR)
from jinja2 import Environment, FileSystemLoader

# =====================================================
# PROTEÇÃO DO WEASYPRINT (WINDOWS SAFE)
# =====================================================
HTML = None
try:
    from weasyprint import HTML
except Exception:
    print("⚠️ WeasyPrint não disponível neste ambiente (Windows). PDF será gerado apenas no Linux (Render).")

# =====================================================
# APP
# =====================================================
app = FastAPI(title="API Solarx - Faturas & OCR")

# =====================================================
# PASTAS TEMPORÁRIAS
# =====================================================
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Pasta específica para OCR
TEMP_OCR_DIR = BASE_DIR / "temp_ocr"
TEMP_OCR_DIR.mkdir(exist_ok=True)

# =====================================================
# TEMPLATE ENGINE
# =====================================================
env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=True
)

# =====================================================
# DADOS FIXOS DA EMPRESA
# =====================================================
EMPRESA = {
    "marca": "SOLARX",
    "razao_social": "SOLMAIS DISTRIBUIDORA",
    "cnpj": "XX.XXX.XXX/0001-XX",
    "endereco": "Endereço completo da Solmais Distribuidora",
    "representante": "JOAQUIM FERNANDES",
    "email": "contato@solmais.com.br"
}


# =====================================================
# CÁLCULO DE ECONOMIA
# =====================================================
def calcular_economia(valor_fatura: float, percentual: float = 0.10):
    if not valor_fatura:
        return {
            "percentual_desconto": 0,
            "economia_mensal": 0,
            "economia_anual": 0,
            "valor_com_desconto": 0
        }

    economia_mensal = round(valor_fatura * percentual, 2)
    economia_anual = round(economia_mensal * 12, 2)
    valor_com_desconto = round(valor_fatura - economia_mensal, 2)

    return {
        "percentual_desconto": int(percentual * 100),
        "economia_mensal": economia_mensal,
        "economia_anual": economia_anual,
        "valor_com_desconto": valor_com_desconto
    }


# =====================================================
# ROTA 1: GERA PROPOSTA (PDF DIGITAL)
# =====================================================
@app.post("/gerar-proposta")
async def gerar_proposta(
        pdf: UploadFile = File(...),
        senha: str = Form(None)
):
    temp_pdf = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    with open(temp_pdf, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    try:
        resultado_completo = process_copel_bill(temp_pdf)
        data = resultado_completo["dados_extraidos"]

        # Logica de Negocio
        total_pagar = data["referencia_fatura"]["total_pagar"]
        economia = calcular_economia(total_pagar)

        if HTML is None:
            return {
                "status": "ok",
                "mensagem": "PDF Gerado apenas no Linux. Aqui estão os dados processados.",
                "dados_extraidos": data,
                "economia": economia
            }

        template = env.get_template("proposta.html")
        html_renderizado = template.render(
            **data,
            empresa=EMPRESA,
            economia=economia
        )

        pdf_final = HTML(string=html_renderizado).write_pdf()

        return Response(
            content=pdf_final,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=proposta.pdf"}
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

    finally:
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except:
                pass


# =====================================================
# ROTA 2: LEITURA DE FOTO (OCR) - NOVA!
# =====================================================
@app.post("/ler-fatura-foto")
async def ler_fatura_foto(file: UploadFile = File(...)):
    filename = file.filename.lower()
    if not filename.endswith(('.jpg', '.jpeg', '.png')):
        raise HTTPException(status_code=400, detail="Apenas imagens (.jpg, .png)")

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1]
    temp_img_path = TEMP_OCR_DIR / f"{file_id}{ext}"

    try:
        # Salva a imagem
        with open(temp_img_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"📸 Foto recebida na API Principal: {temp_img_path}")

        # Chama a função de OCR que criamos
        resultado = process_image_bill(temp_img_path)

        if isinstance(resultado, dict):
            resultado["_info_api"] = "Processado via API Unificada"

        return JSONResponse(content=resultado)

    except Exception as e:
        print(f"❌ Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_img_path.exists():
            try:
                temp_img_path.unlink()
            except:
                pass