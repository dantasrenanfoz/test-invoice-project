from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response
from pathlib import Path
import shutil
import uuid

from extractor import extract_pdf, extract_fields
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
app = FastAPI()

# =====================================================
# PASTAS TEMPORÁRIAS
# =====================================================
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

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
# CÁLCULO DE ECONOMIA (MODELO ALEXANDRIA)
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
# ROTA ÚNICA — GERA PDF FINAL
# =====================================================
@app.post("/gerar-proposta")
async def gerar_proposta(
    pdf: UploadFile = File(...),
    senha: str = Form(...)
):
    temp_pdf = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    with open(temp_pdf, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    try:
        # 1️⃣ Extrai dados da fatura
        page, words, text = extract_pdf(temp_pdf, senha)
        data = extract_fields(page, words, text)

        # 2️⃣ Calcula economia
        economia = calcular_economia(
            data["referencia_fatura"]["total_pagar"]
        )

        # ⚠️ WINDOWS: WeasyPrint indisponível
        if HTML is None:
            return {
                "status": "ok",
                "mensagem": "Extração realizada com sucesso.",
                "observacao": "Geração de PDF ocorre apenas no ambiente Linux (Render).",
                "dados_extraidos": data,
                "economia": economia
            }

        # 3️⃣ Renderiza HTML
        template = env.get_template("proposta.html")
        html_renderizado = template.render(
            **data,
            empresa=EMPRESA,
            economia=economia
        )

        # 4️⃣ Converte HTML → PDF
        pdf_final = HTML(string=html_renderizado).write_pdf()

        # 5️⃣ Retorna PDF
        return Response(
            content=pdf_final,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "inline; filename=proposta.pdf"
            }
        )

    finally:
        temp_pdf.unlink(missing_ok=True)
