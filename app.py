from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response, JSONResponse
from pathlib import Path
import shutil
import uuid
import os

# =====================================================
# MUDANÇA 1: Importamos a nova função única do extrator
# =====================================================
from extractor import process_copel_bill
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
# ROTA ÚNICA — GERA PDF FINAL
# =====================================================
@app.post("/gerar-proposta")
async def gerar_proposta(
        pdf: UploadFile = File(...),
        senha: str = Form(None)  # Senha opcional
):
    # Gera um nome único para o arquivo
    temp_pdf = TEMP_DIR / f"{uuid.uuid4()}.pdf"

    # Salva o arquivo no disco
    with open(temp_pdf, "wb") as f:
        shutil.copyfileobj(pdf.file, f)

    try:
        # =====================================================
        # MUDANÇA 2: Nova Lógica de Extração
        # =====================================================
        # O novo extrator faz tudo sozinho: abre, lê e estrutura.
        # Ele retorna um dicionário completo.
        resultado_completo = process_copel_bill(temp_pdf)

        # Acessamos a parte que interessa: 'dados_extraidos'
        data = resultado_completo["dados_extraidos"]

        # =====================================================
        # Lógica de Negócio (Mantida)
        # =====================================================

        # Pega o total extraído (agora vindo corretamente via âncoras)
        total_pagar = data["referencia_fatura"]["total_pagar"]

        # Calcula economia
        economia = calcular_economia(total_pagar)

        # ⚠️ WINDOWS: Se não tiver WeasyPrint, retorna o JSON para conferência
        if HTML is None:
            return {
                "status": "ok",
                "mensagem": "PDF Gerado apenas no Linux. Aqui estão os dados processados.",
                "dados_extraidos": data,
                "economia": economia
            }

        # 3️⃣ Renderiza HTML (Preenche o template com os dados novos)
        template = env.get_template("proposta.html")
        html_renderizado = template.render(
            **data,  # Espalha os dados (concessionaria, cliente, itens...)
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

    except Exception as e:
        # Se der erro, retorna 500 com a mensagem
        import traceback
        traceback.print_exc()  # Printa erro no terminal
        return JSONResponse(status_code=500, content={"error": str(e)})

    finally:
        # Limpeza do arquivo temporário
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except:
                pass