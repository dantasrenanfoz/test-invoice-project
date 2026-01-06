import pdfplumber
import platform
import numpy as np
import re
import pypdfium2 as pdfium
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from paddleocr import PaddleOCR
from extractor import CopelExtractor
from PIL import Image

app = FastAPI()
ex = CopelExtractor()
_ocr_model = None


def get_ocr():
    global _ocr_model
    if _ocr_model is None:
        # Nota: O Render Free tier pode derrubar o processo por falta de RAM aqui
        _ocr_model = PaddleOCR(lang="pt", use_angle_cls=True, show_log=False, use_gpu=False)
    return _ocr_model


def extract_text_ocr(pdf_path: Path):
    """Converte PDF para imagem usando pypdfium2 e aplica OCR"""
    pdf = pdfium.PdfDocument(str(pdf_path))
    ocr = get_ocr()
    lines = []

    for i in range(len(pdf)):
        page = pdf[i]
        # Renderiza a página (escala 3 dá ~216 DPI, economiza memória no Render)
        bitmap = page.render(scale=3)
        pil_image = bitmap.to_pil()

        # Converte para formato que o Paddle entende
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
        # 1. Tenta extração de texto direto (Rápido e leve)
        with pdfplumber.open(temp_path) as p:
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        fonte = "PDF_TEXT"

        # 2. Se o texto for insuficiente, tenta OCR (Pesado)
        if len(raw_text.strip()) < 300:
            fonte = "OCR"
            raw_text = extract_text_ocr(temp_path)

        # Processamento de dados
        topo_text = raw_text[:3000]
        cliente_section = ex.safe_search(r"Nome:.*", topo_text, group=0) or topo_text

        cidade_raw = ex.safe_search(r'Cidade:\s*([A-Za-z\s\.]+)', cliente_section)
        estado_raw = ex.safe_search(r'Estado:\s*([A-Z]{2})', cliente_section)
        cidade_uf = f"{cidade_raw} - {estado_raw}" if cidade_raw and estado_raw else (cidade_raw or "")

        nome = ex.safe_search(r"Nome:\s*(.*?)\s*Endereço", cliente_section)
        uc = ex.safe_search(r"UNIDADE CONSUMIDORA\s+(\d+)", raw_text) or \
             ex.safe_search(r"(\d{8,})\s+\d{2}/\d{4}", raw_text)

        doc_cliente = ex.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", cliente_section)
        cep_cliente = ex.safe_search(r"CEP:\s*(\d{5}-\d{3})", cliente_section)

        ref_bloco = re.search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$([\d\.,]+)", raw_text)
        mes_ref = ref_bloco.group(1) if ref_bloco else ex.safe_search(r"REF\.\s*M[EÊ]S.*?(\d{2}/\d{4})", raw_text)
        vencimento = ref_bloco.group(2) if ref_bloco else ex.safe_search(r"VENCIMENTO\s+(\d{2}/\d{2}/\d{4})", raw_text)
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path.exists():
            temp_path.unlink()