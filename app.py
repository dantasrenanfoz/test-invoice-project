import pdfplumber
import platform
import numpy as np
import re
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from pdf2image import convert_from_path
from paddleocr import PaddleOCR
from extractor import CopelExtractor

app = FastAPI()
ex = CopelExtractor()
_ocr_model = None


def get_ocr():
    global _ocr_model
    if _ocr_model is None:
        _ocr_model = PaddleOCR(lang="pt", use_angle_cls=True, show_log=False, use_gpu=False)
    return _ocr_model


@app.post("/ler-fatura-pdf")
async def ler_fatura(pdf: UploadFile = File(...)):
    temp_path = Path(f"temp_{pdf.filename}")
    with open(temp_path, "wb") as buffer:
        buffer.write(await pdf.read())

    try:
        with pdfplumber.open(temp_path) as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        fonte = "PDF_TEXT"
        if len(raw_text.strip()) < 300:
            fonte = "OCR"
            images = convert_from_path(temp_path, dpi=300)
            ocr = get_ocr()
            lines = [line[1][0] for img in images for res in ocr.ocr(np.array(img), cls=True) if res for line in res[0]]
            raw_text = "\n".join(lines)

        # DEBUG: Caso ainda tenha dúvida, descomente a linha abaixo para ver o texto no terminal
        # print(raw_text)

        topo_text = raw_text[:3000]
        # Isolamos a seção que contém os dados do cliente
        cliente_section = ex.safe_search(r"Nome:.*", topo_text, group=0) or topo_text

        # Cabeçalho
        nome = ex.safe_search(r"Nome:\s*(.*?)\s*Endereço", cliente_section)
        uc = ex.safe_search(r"UNIDADE CONSUMIDORA\s+(\d+)", raw_text) or \
             ex.safe_search(r"(\d{8,})\s+\d{2}/\d{4}", raw_text)

        doc_cliente = ex.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", cliente_section)
        cep_cliente = ex.safe_search(r"CEP:\s*(\d{5}-\d{3})", cliente_section)

        # Cidade/UF tratamento Python 3.10
        cidade_raw = ex.safe_search(r'Cidade:\s*([A-Za-z\s]+)', cliente_section)
        estado_raw = ex.safe_search(r'Estado:\s*([A-Z]{2})', cliente_section)
        cidade_uf = f"{cidade_raw} - {estado_raw}" if cidade_raw and estado_raw else (cidade_raw or "")

        # Referência
        ref_bloco = re.search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$([\d\.,]+)", raw_text)
        mes_ref = ref_bloco.group(1) if ref_bloco else ex.safe_search(r"(\d{2}/\d{4})\s+\d{2}/\d{2}/\d{4}", raw_text)
        vencimento = ref_bloco.group(2) if ref_bloco else ex.safe_search(r"\d{2}/\d{4}\s+(\d{2}/\d{2}/\d{4})", raw_text)
        total = ex.br_money_to_float(ref_bloco.group(3)) if ref_bloco else \
            ex.br_money_to_float(ex.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", raw_text))

        return {
            "arquivo": pdf.filename,
            "fonte": fonte,
            "cliente": {
                "nome": nome,
                "uc": uc,
                "cnpj_cpf": doc_cliente,
                "endereco": ex.safe_search(r"Endereço:\s*(.*?)\s*CEP", cliente_section),
                "cep": cep_cliente,
                "cidade_uf": cidade_uf
            },
            "referencia": {
                "mes": mes_ref,
                "vencimento": vencimento,
                "total": total
            },
            "itens": ex.extract_itens_financeiros(raw_text),
            "medicao": ex.extract_medicao(raw_text),
            "geracao_distribuida": ex.extract_scee(raw_text),
            "tributos": ex.extract_tributos(raw_text),
            "historico": ex.extract_historico(raw_text),
            "metadados": {
                "chave_acesso": (ex.safe_search(r"Chave de Acesso\s*([\d\s]{40,})", raw_text) or "").replace(" ", ""),
                "protocolo": ex.safe_search(r"Protocolo de Autorização:\s*(\d+)", raw_text)
            }
        }
    finally:
        if temp_path.exists(): temp_path.unlink()