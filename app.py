from fastapi import FastAPI, UploadFile, File
import pdfplumber
from extractor import CopelExtractor
import os

app = FastAPI()
ex = CopelExtractor()


@app.post("/ler-fatura-pdf")
async def ler_fatura(pdf: UploadFile = File(...)):
    # Salva temporário
    with open("temp.pdf", "wb") as f:
        f.write(await pdf.read())

    try:
        with pdfplumber.open("temp.pdf") as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        cliente = ex.extract_cliente_info(raw_text)
        fatura = ex.extract_fatura_dados(raw_text)
        itens = ex.extract_itens_faturados(raw_text)
        hist = ex.extract_historicos(raw_text)

        # Cálculo da Tarifa Líquida Total (TE + TUSD sem impostos)
        tarifa_te = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TE"), 0)
        tarifa_tusd = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TUSD"), 0)

        # Valor da IP isolado
        valor_ip = next((i['valor_bruto'] for i in itens if i['tipo'] == "IP"), 0)

        return {
            "status": "sucesso",
            "cliente": cliente,
            "fatura": fatura,
            "itens": itens,
            "historicos": {"registros": hist},
            "analise_assina": {
                "tarifa_liquida_total": tarifa_te + tarifa_tusd,
                "valor_ip": valor_ip,
                "kwh_disponibilidade": cliente['kwh_disponibilidade'],
                "regime_gd": cliente['regime_gd']
            }
        }
    except Exception as e:
        return {"status": "erro", "msg": str(e)}
    finally:
        if os.path.exists("temp.pdf"): os.remove("temp.pdf")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)