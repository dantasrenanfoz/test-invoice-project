from fastapi import FastAPI, UploadFile, File
import pdfplumber
import os
import re
from extractor import CopelExtractor

app = FastAPI()
ex = CopelExtractor()

@app.post("/ler-fatura-pdf")
async def ler_fatura(pdf: UploadFile = File(...)):
    temp_path = f"temp_{pdf.filename}"
    content = await pdf.read()
    with open(temp_path, "wb") as buffer:
        buffer.write(content)

    try:
        with pdfplumber.open(temp_path) as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        cliente = ex.extract_cliente_info(raw_text)
        fatura = ex.extract_fatura_dados(raw_text)
        medicoes = ex.extract_medicoes(raw_text)
        itens = ex.extract_itens_faturados(raw_text)
        scee = ex.extract_scee(raw_text)

        # Totais de Energia
        cons_kwh = sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'CONSUMO')
        ger_mes_kwh = sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'GERACAO')
        ger_leitura_atual = sum(m['leitura_atual'] for m in medicoes if m['tipo'] == 'GERACAO')
        compensada_kwh = abs(sum(i['valor'] for i in itens if i['tipo'] == "CREDITO"))

        # Campos Assina (Cálculo do Papel)
        tarifa_te = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TE"), 0)
        tarifa_tusd = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TUSD"), 0)
        valor_ip = next((i['valor'] for i in itens if i['tipo'] == "IP"), 0)

        return {
            "cliente": cliente,
            "fatura": fatura,
            "energia": {
                "consumo_kwh": cons_kwh,
                "geracao_kwh": ger_leitura_atual,
                "geracao_mes_kwh": ger_mes_kwh,
                "energia_compensada_kwh": compensada_kwh,
                "saldo_creditos_kwh": scee.get("saldos", {}).get("acumulado", {}).get("tp", 0)
            },
            "analise_financeira_assina": {
                "base_tarifa_liquida_kwh": tarifa_te + tarifa_tusd,
                "custo_fixo_ip": valor_ip,
                "consumo_isento_taxa": cliente['kwh_disponibilidade']
            },
            "itens_faturados": itens,
            "unidade": {
                "codigo_uc": cliente['uc'],
                "tipo_fase": cliente['tipo_fase'],
                "regime_gd": cliente['regime_gd']
            }
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)