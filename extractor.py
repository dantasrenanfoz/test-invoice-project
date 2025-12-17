import pdfplumber
import re
from pathlib import Path

# ===============================
# CONFIGURAÇÕES
# ===============================
DEBUG_EXPORT_CROPS = False
DEBUG_DIR = Path("debug_crops")
DEBUG_DIR.mkdir(exist_ok=True)

# ===============================
# UTILIDADES
# ===============================
def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def br_money_to_float(v):
    if not v:
        return None
    try:
        return float(v.replace(".", "").replace(",", "."))
    except:
        return None


def find_first(pattern, text, flags=0):
    if not text:
        return None
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def safe_int(v):
    try:
        return int(v)
    except:
        return None


def safe_crop(page, bbox):
    x0, y0, x1, y1 = bbox
    px0, py0, px1, py1 = page.bbox

    x0 = max(px0, x0)
    y0 = max(py0, y0)
    x1 = min(px1, x1)
    y1 = min(py1, y1)

    if x1 <= x0 or y1 <= y0:
        return None

    return page.crop((x0, y0, x1, y1))


def export_crop(crop, name):
    if not DEBUG_EXPORT_CROPS or not crop:
        return
    img = crop.to_image(resolution=200)
    img.save(DEBUG_DIR / f"{name}.png")


# ===============================
# NORMALIZAÇÕES
# ===============================
def normalize_fases(v):
    if not v:
        return None
    v = v.lower()
    if "mono" in v:
        return "mono"
    if "bi" in v:
        return "bi"
    if "tri" in v:
        return "tri"
    return v


MESES = {
    "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04",
    "MAI": "05", "JUN": "06", "JUL": "07", "AGO": "08",
    "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12"
}

def normalize_mes_ano(v):
    if not v or len(v) != 5:
        return v
    mes = MESES.get(v[:3])
    ano = "20" + v[3:]
    if mes:
        return f"{mes}/{ano}"
    return v


def clean_logradouro(v):
    if not v:
        return None
    v = re.sub(r"CEP.*", "", v, flags=re.IGNORECASE)
    v = re.sub(r"Cidade:.*", "", v, flags=re.IGNORECASE)
    return normalize(v)


# ===============================
# PDF
# ===============================
def extract_pdf(pdf_path, password):
    with pdfplumber.open(pdf_path, password=password) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(use_text_flow=True)
        text = page.extract_text() or ""
        text = text.replace("\u00A0", " ")
        return page, words, text


# ===============================
# EXTRAÇÕES ESPECÍFICAS
# ===============================
def extract_uc_ref_venc_total(page):
    bboxes = [
        (260, 240, 560, 360),
        (260, 260, 560, 390),
        (260, 220, 560, 340),
    ]

    data = {"uc": None, "mes": None, "venc": None, "total": None}

    for i, bbox in enumerate(bboxes):
        crop = safe_crop(page, bbox)
        if not crop:
            continue

        export_crop(crop, f"box_uc_{i}")
        t = crop.extract_text() or ""

        if not data["uc"]:
            m = re.search(r"\b([A-Z]{1,3}\s*\d{8,10}|\d{8,10})\b", t)
            if m:
                data["uc"] = normalize(m.group(1))

        if not data["mes"]:
            m = re.search(r"\b(\d{2}/\d{4})\b", t)
            if m:
                data["mes"] = m.group(1)

        if not data["venc"]:
            m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", t)
            if m:
                data["venc"] = m.group(1)

        if not data["total"]:
            m = re.search(r"R\$\s*([\d\.,]+)", t)
            if m:
                data["total"] = br_money_to_float(m.group(1))

        if all(data.values()):
            break

    return data


def extract_historico(text):
    hist = []
    for m in re.finditer(r"([A-Z]{3}\d{2})\s+(\d+)\s+(\d{1,2})", text):
        hist.append({
            "mes": normalize_mes_ano(m.group(1)),
            "kwh": int(m.group(2)),
            "dias": int(m.group(3))
        })

    uniq = []
    seen = set()
    for h in hist:
        k = (h["mes"], h["kwh"], h["dias"])
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq


def extract_itens_fatura(page):
    itens = []

    bbox = (40, 380, 540, 660)
    crop = safe_crop(page, bbox)
    export_crop(crop, "itens_fatura")

    if not crop:
        return itens

    text = crop.extract_text() or ""
    lines = [normalize(l) for l in text.split("\n") if len(l.strip()) > 3]

    for l in lines:
        m = re.match(
            r"([A-ZÇ\. ]+)\s+(kWh|UN)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)",
            l
        )
        if m:
            itens.append({
                "descricao": m.group(1).strip(),
                "unidade": m.group(2),
                "quantidade": float(m.group(3).replace(",", ".")),
                "valor_unitario": br_money_to_float(m.group(4)),
                "valor_total": br_money_to_float(m.group(5))
            })

    return itens


def extract_impostos(text):
    impostos = {}

    for trib in ["ICMS", "PIS", "COFINS"]:
        base = find_first(fr"{trib}\s+([\d\.,]+)", text)
        aliq = find_first(fr"{trib}.*?(\d+,\d+)%", text)
        valor = find_first(fr"{trib}.*?([\d\.,]+)$", text, re.MULTILINE)

        impostos[trib.lower()] = {
            "base_calculo": br_money_to_float(base),
            "aliquota_percentual": float(aliq.replace(",", ".")) if aliq else None,
            "valor": br_money_to_float(valor)
        }

    return impostos


# ===============================
# EXTRAÇÃO PRINCIPAL
# ===============================
def extract_fields(page, words, text):
    header = extract_uc_ref_venc_total(page)

    return {
        "concessionaria": {
            "nome": "COPEL DISTRIBUIÇÃO S.A.",
            "cnpj": "04.368.898/0001-06",
            "inscricao_estadual": "9023307399",
            "site": "www.copel.com"
        },
        "cliente": {
            "nome": find_first(r"Nome:\s*([^\n]+)", text),
            "cpf": find_first(r"CPF:\s*([0-9\.\-*]+)", text),
            "endereco": {
                "logradouro": clean_logradouro(
                    find_first(
                        r"Endereço:\s*(.*?)\s*(CEP|Cidade:)",
                        text,
                        re.DOTALL
                    )
                ),
                "cidade": find_first(r"Cidade:\s*([A-Za-zÀ-ÿ ]+)", text),
                "uf": find_first(r"Estado:\s*([A-Z]{2})", text),
                "cep": find_first(r"(\d{5}-\d{3})", text)
            }
        },
        "contrato": {
            "unidade_consumidora": header["uc"],
            "classificacao": find_first(r"Classifica[cç][aã]o:\s*(.+)", text),
            "subgrupo": find_first(r"\b(B[1-4]|A[1-4]|A3A|AS)\b", text),
            "tipo_fornecimento": {
                "descricao": find_first(r"Tipo de Fornecimento:\s*(.+)", text),
                "corrente": find_first(r"/\s*(\d+A)", text),
                "fases": normalize_fases(
                    find_first(r"(mono|bi|tri)f[aá]sico", text, re.IGNORECASE)
                )
            }
        },
        "referencia_fatura": {
            "mes_referencia": header["mes"],
            "vencimento": header["venc"],
            "total_pagar": header["total"]
        },
        "leituras": {
            "leitura_anterior": find_first(r"Leitura anterior\s*(\d{2}/\d{2}/\d{4})", text),
            "leitura_atual": find_first(r"Leitura atual\s*(\d{2}/\d{2}/\d{4})", text),
            "numero_dias": safe_int(find_first(r"N[ºo]\s*de\s*dias\s*(\d+)", text)),
            "proxima_leitura": find_first(r"Pr[óo]xima Leitura\s*(\d{2}/\d{2}/\d{4})", text)
        },
        "medidor": {
            "numero": find_first(r"Medidor\s+(\d{8,12})", text),
            "leitura_anterior": find_first(r"Leitura Anterior\s*(\d+)", text),
            "leitura_atual": find_first(r"Leitura Atual\s*(\d+)", text),
            "constante": 1,
            "consumo_kwh": safe_int(find_first(r"Consumo\s*kWh\s*(\d+)", text))
        },
        "itens_fatura": extract_itens_fatura(page),
        "impostos": extract_impostos(text),
        "historico_consumo": extract_historico(text),
        "fiscal": {
            "numero_fatura": find_first(r"N[uú]mero da fatura:\s*([A-Z0-9\-]+)", text),
            "data_emissao": find_first(r"DATA DE EMISS[AÃ]O:\s*(\d{2}/\d{2}/\d{4})", text)
        }
    }
