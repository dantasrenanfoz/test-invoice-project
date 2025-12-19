from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import uuid
import os

# =====================================================
# IMPORTAÇÕES DOS EXTRATORES
# =====================================================
from extractor import process_copel_bill
from extractor_ocr import process_image_bill
from jinja2 import Environment, FileSystemLoader

# =====================================================
# WEASYPRINT (OBRIGATÓRIO PARA PDF)
# =====================================================
try:
    from weasyprint import HTML
except Exception as e:
    HTML = None
    print("❌ ERRO CRÍTICO: WeasyPrint não disponível:", e)

# =====================================================
# APP
# =====================================================
app = FastAPI(title="API Solarx - Faturas & OCR")

# ===================== 🔐 CORS =====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://93.127.212.221:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ==================================================

# =====================================================
# PASTAS TEMPORÁRIAS
# =====================================================
BASE_DIR = Path(__file__).parent

TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

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
# ROTA: GERA PROPOSTA (PDF SEMPRE)
# =====================================================
@app.post("/gerar-proposta")
async def gerar_proposta(
    pdf: UploadFile = File(...),
    senha: str = Form(None)
):
    if HTML is None:
        raise HTTPException(
            status_code=500,
            detail="WeasyPrint não está disponível no ambiente. PDF não pode ser gerado."
        )

    temp_pdf = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    with open(temp_pdf, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    try:
        resultado = process_copel_bill(temp_pdf)
        data = resultado["dados_extraidos"]

        # ===============================
        # GARANTIA DE TOTAL A PAGAR
        # ===============================
        total_pagar = data.get("referencia_fatura", {}).get("total_pagar")
        if not total_pagar:
            total_pagar = 1.0
            data["referencia_fatura"]["total_pagar"] = total_pagar

        economia = calcular_economia(total_pagar)

        # ===============================
        # MÉDIA DE CONSUMO (kWh)
        # ===============================
        historico = data.get("historico_consumo", [])
        if historico:
            media_consumo_kwh = round(
                sum(h["kwh"] for h in historico) / len(historico),
                2
            )
        else:
            media_consumo_kwh = 0

        # ===============================
        # RENDERIZA PDF
        # ===============================
        template = env.get_template("proposta.html")
        html_renderizado = template.render(
            **data,
            empresa=EMPRESA,
            economia=economia,
            media_consumo_kwh=media_consumo_kwh
        )

        pdf_final = HTML(string=html_renderizado).write_pdf()

        return Response(
            content=pdf_final,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "inline; filename=proposta.pdf"
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except:
                pass

# =====================================================
# ROTA: LEITURA DE FOTO (OCR)
# =====================================================
@app.post("/ler-fatura-foto")
async def ler_fatura_foto(file: UploadFile = File(...)):
    filename = file.filename.lower()

    if not filename.endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(
            status_code=400,
            detail="Apenas imagens JPG ou PNG são permitidas"
        )

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1]
    temp_img = TEMP_OCR_DIR / f"{file_id}{ext}"

    try:
        with open(temp_img, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        resultado = process_image_bill(temp_img)

        if isinstance(resultado, dict):
            resultado["_info_api"] = "Processado via API Unificada"

        return JSONResponse(content=resultado)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_img.exists():
            try:
                temp_img.unlink()
            except:
                pass
