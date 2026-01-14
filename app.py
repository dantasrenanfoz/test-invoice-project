from fastapi import FastAPI, UploadFile, File
import pdfplumber
import io
import re
from extractor import CopelExtractor

app = FastAPI(title="Lex Energia Clone API PRO")
ex = CopelExtractor()


@app.post("/processar-fatura")
async def processar_fatura(pdf: UploadFile = File(...)):
    try:
        content = await pdf.read()
        with pdfplumber.open(io.BytesIO(content)) as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        # Extração massiva
        dados = ex.extract_all(raw_text)

        # Inteligência Adicional (Cálculos de Economia e Chave)
        itens = dados['itens']
        inj = sum(abs(i['quantidade']) for i in itens if i['tipo'] == "INJETADA")
        cons = sum(i['quantidade'] for i in itens if i['tipo'] in ["TE", "TUSD"] and i['quantidade'] > 0)

        # Captura Chave de Acesso (44 dígitos)
        chave = re.sub(r"\s+", "", ex.safe_search(r"Chave de Acesso\s*([\d\s]{44,})", raw_text) or "")

        dados["analise_energia_solar"] = {
            "total_consumido_kwh": cons,
            "total_injetado_kwh": inj,
            "percentual_abatimento": round((inj / cons) * 100, 2) if cons > 0 else 0,
            "chave_acesso": chave
        }

        return dados

    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)