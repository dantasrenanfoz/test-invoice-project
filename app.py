from fastapi import FastAPI, UploadFile, File, HTTPException
import pdfplumber
import io
import uvicorn
from extractor import CopelExtractor

app = FastAPI(title="Lex Energia Extractor API")
ex = CopelExtractor()


@app.post("/processar-fatura")
async def processar_fatura(pdf: UploadFile = File(...)):
    # Validação simples de arquivo
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="O arquivo enviado deve ser um PDF.")

    try:
        content = await pdf.read()

        with pdfplumber.open(io.BytesIO(content)) as p:
            # Extrai texto de todas as páginas
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        if not raw_text.strip():
            raise HTTPException(status_code=422, detail="Não foi possível extrair texto do PDF (pode ser uma imagem).")

        # Extração completa usando a classe CopelExtractor
        dados = ex.extract_all(raw_text)

        # Inteligência de Negócio: Cálculos de Energia Solar
        itens = dados['itens']
        inj = sum(abs(i['quantidade']) for i in itens if i['tipo'] == "INJETADA")
        cons = sum(i['quantidade'] for i in itens if i['tipo'] in ["TE", "TUSD"] and i['quantidade'] > 0)

        dados["analise_energia_solar"] = {
            "total_consumido_kwh": round(cons, 2),
            "total_injetado_kwh": round(inj, 2),
            "percentual_abatimento": round((inj / cons) * 100, 2) if cons > 0 else 0,
            "chave_acesso": dados['fatura'].get('chave_acesso')
        }

        return dados

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)