import numpy as np
import pypdfium2 as pdfium
import pdfplumber
import re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from paddleocr import PaddleOCR
from extractor import CopelExtractor

app = FastAPI(title="Parser Copel PRO - Lex Style")
ex = CopelExtractor()
_ocr_model = None


def get_ocr():
    global _ocr_model
    if _ocr_model is None:
        _ocr_model = PaddleOCR(lang="pt", use_angle_cls=True, show_log=False, use_gpu=False)
    return _ocr_model


def extract_text_ocr(pdf_path: Path):
    pdf = pdfium.PdfDocument(str(pdf_path))
    ocr = get_ocr()
    lines = []
    for i in range(min(len(pdf), 2)):
        page = pdf[i]
        bitmap = page.render(scale=3)
        pil_image = bitmap.to_pil()
        img_array = np.array(pil_image)
        res = ocr.ocr(img_array, cls=True)
        if res and res[0]:
            for line in res[0]:
                lines.append(line[1][0])
    pdf.close()
    return "\n".join(lines)


@app.post("/ler-fatura-pdf")
async def ler_fatura(pdf: UploadFile = File(...)):
    temp_path = Path(f"temp_{pdf.filename}")
    content = await pdf.read()
    with open(temp_path, "wb") as buffer:
        buffer.write(content)

    try:
        with pdfplumber.open(temp_path) as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        fonte = "PDF_TEXT"
        if len(raw_text.strip()) < 500:
            fonte = "OCR"
            raw_text = extract_text_ocr(temp_path)

        # 1. Extração via Extractor
        cliente = ex.extract_cliente_info(raw_text)
        fatura = ex.extract_fatura_dados(raw_text)
        medicoes = ex.extract_medicoes(raw_text)
        itens = ex.extract_itens_faturados(raw_text)
        scee = ex.extract_scee(raw_text)
        hist = ex.extract_historicos(raw_text)
        leitura = ex.extract_leitura_status(raw_text)
        trib = ex.extract_tributos(raw_text)
        band = ex.extract_bandeiras(raw_text)

        # 2. Consolidação de Negócio (Ajustada conforme solicitado)
        cons_kwh = sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'CONSUMO')

        # Geração Mensal (Rendimento do período)
        ger_mes_kwh = sum(m['valor_apurado'] for m in medicoes if m['tipo'] == 'GERACAO')

        # MUDANÇA SOLICITADA: geracao_kwh agora é a LEITURA ATUAL (Odômetro acumulado)
        ger_leitura_atual = sum(m['leitura_atual'] for m in medicoes if m['tipo'] == 'GERACAO')

        compensada_kwh = abs(sum(i['quantidade'] for i in itens if i['tipo'] == 'INJETADA'))

        # Lógica de Tipo de Unidade
        tem_linha_geracao = any(m['tipo'] == 'GERACAO' for m in medicoes)
        tipo_unidade = "CONSUMIDORA"
        if tem_linha_geracao or scee.get("tipo") == "MICROGERADORA":
            tipo_unidade = "MICROGERADORA"
        elif scee.get("participa"):
            tipo_unidade = "BENEFICIARIA_SCEE"

        return {
            "documento": {
                "concessionaria": "COPEL",
                "tipo": "NF3E",
                "arquivo_nome": pdf.filename,
                "fonte_extracao": fonte,
                "versao_parser": "copel-parser-v2.1-final"
            },
            "unidade": {
                "codigo_uc": cliente['uc'],
                "tipo": tipo_unidade,
                "classe": ex.safe_search(r"(B\d\s+[A-Za-z/ ]+)", raw_text),
                "possui_gd": tipo_unidade != "CONSUMIDORA"
            },
            "cliente": cliente,
            "fatura": fatura,
            "leitura": leitura,
            "medicao": {"registros": medicoes},
            "energia": {
                "consumo_kwh": cons_kwh,
                "geracao_kwh": ger_leitura_atual,  # Valor solicitado: Leitura Atual (Ex: 98086)
                "geracao_mes_kwh": ger_mes_kwh,  # Rendimento do mês (Ex: 0 ou 15454)
                "energia_compensada_kwh": compensada_kwh,
                "saldo_creditos_kwh": scee.get("saldos", {}).get("acumulado", {}).get("tp", 0)
            },
            "itens_faturados": itens,
            "tributos": trib,
            "scee": scee,
            "historicos": hist,
            "bandeiras_tarifarias": band,
            "nf3e": {
                "chave_acesso": (ex.safe_search(r"Chave de Acesso\s*([\d\s]{40,})", raw_text) or "").replace(" ", ""),
                "protocolo": ex.safe_search(r"Protocolo de Autorização:\s*(\d+)", raw_text)
            },
            "auditoria": {
                "confianca_extracao": 0.99 if fonte == "PDF_TEXT" else 0.85,
                "alertas": [leitura['descricao']] if leitura['impacta_simulacao'] else []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha técnica: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()