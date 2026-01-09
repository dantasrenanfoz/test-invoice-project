from fastapi import FastAPI, UploadFile, File
import pdfplumber
import os
import re
from extractor import CopelExtractor

app = FastAPI(title="Parser Copel Total - Assina Energy")
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

        # Executa todas as extrações
        cliente = ex.extract_cliente_info(raw_text)
        fatura = ex.extract_fatura_dados(raw_text)
        medicoes = ex.extract_medicoes(raw_text)
        itens = ex.extract_itens_faturados(raw_text)
        scee = ex.extract_scee(raw_text)
        historicos = ex.extract_historicos(raw_text)
        tributos = ex.extract_tributos(raw_text)

        # Lógica de Classificação
        tem_linha_geracao = any(m['tipo'] == 'GERACAO' for m in medicoes)
        tipo_unidade = "UC (Consumo)"
        if tem_linha_geracao:
            tipo_unidade = "USINA (Geradora)"
        elif scee.get("participa"):
            tipo_unidade = "UC Beneficiária (GD)"

        # Inteligência Assina (Cálculo do Papel)
        tarifa_te = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TE"), 0)
        tarifa_tusd = next((i['tarifa_liquida'] for i in itens if i['tipo'] == "TUSD"), 0)
        valor_ip = next((i['valor'] for i in itens if i['tipo'] == "IP"), 0)

        return {
            "documento": {
                "arquivo": pdf.filename,
                "tipo_unidade": tipo_unidade,
                "chave": re.sub(r"\s+", "", ex.safe_search(r"Chave de Acesso\s*([\d\s]{40,})", raw_text) or "")
            },
            "cliente": cliente,
            "fatura": fatura,
            "energia": {
                "consumo_kwh": sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'CONSUMO'),
                "geracao_mes_kwh": sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'GERACAO'),
                "energia_compensada_kwh": abs(sum(i['quantidade'] for i in itens if i['tipo'] == "INJETADA")),
                "saldo_creditos_kwh": scee.get("saldos", {}).get("acumulado", {}).get("tp", 0)
            },
            "analise_financeira_assina": {
                "base_tarifa_liquida_kwh": tarifa_te + tarifa_tusd,
                "custo_fixo_ip": valor_ip,
                "consumo_isento_taxa": cliente['kwh_disponibilidade']
            },
            "unidade": {
                "codigo_uc": cliente['uc'],
                "tipo_fase": cliente['tipo_fase'],
                "regime_gd": cliente['regime_gd']
            },
            "itens_faturados": itens,
            "medicoes": medicoes,
            "historicos": {"registros": historicos},
            "tributos": tributos
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)