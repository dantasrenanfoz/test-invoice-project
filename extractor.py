import pdfplumber
import re
import json
import os
from pathlib import Path
from groq import Groq

# Configuração da API Groq para Fallback
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
client = Groq(api_key=GROQ_API_KEY)

def normalize(text):
    if not text: return None
    return re.sub(r"\s+", " ", str(text)).strip()

def br_val(v):
    if not v: return 0.0
    if isinstance(v, (int, float)): return float(v)
    v = v.replace("R$", "").replace(".", "").replace(",", ".").strip()
    try: return float(v)
    except: return 0.0

def safe_search(pattern, text, group=1):
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return normalize(m.group(group)) if m else None

# =====================================================
# EXTRAÇÃO DE TABELAS E BLOCOS COMPLEXOS
# =====================================================

def extract_items_completos(page):
    itens = []
    text = page.extract_text() or ""
    # Captura: Descrição, Unidade, Quantidade, Preço Unitário e Valor Total
    pattern = r"(.+?)\s+(kWh|UN)\s+([\d\.,\-]+)\s+([\d\.,]+)\s+([\d\.,\-]+)"
    for line in text.split("\n"):
        m = re.match(pattern, line.strip())
        if m:
            itens.append({
                "descricao": normalize(m.group(1)),
                "unid": m.group(2),
                "quant": br_val(m.group(3)),
                "preco_unit": br_val(m.group(4)),
                "valor_total": br_val(m.group(5))
            })
    return itens

def extract_tributos(text):
    tributos = {}
    for trib in ["ICMS", "PIS", "COFINS"]:
        # Busca a linha do tributo: Tributo | Base | Alíquota | Valor
        m = re.search(rf"{trib}\s+([\d\.,]+)\s+([\d\.,]+)%\s+([\d\.,]+)", text)
        if m:
            tributos[trib.lower()] = {
                "base": br_val(m.group(1)),
                "aliquota": br_val(m.group(2)),
                "valor": br_val(m.group(3))
            }
    return tributos

def extract_scee_completo(text):
    if "SCEE" not in text: return None
    return {
        "uc_geradora": safe_search(r"Geradora\s+DC\s+(\d+)", text) or safe_search(r"Geradora:\s*UC\s*(\d+)", text),
        "saldo_mes_tfp": safe_search(r"Saldo\s+Mes\s+no\s+\(TFP\).*?(\d+)", text),
        "saldo_acumulado_tp": br_val(safe_search(r"Saldo\s+Acumulado\s+no\s+\(TP\).*?([\d\.,]+)", text)),
        "saldo_expirar_prox_mes": br_val(safe_search(r"Saldo\s+a\s+Expirar\s+Proximo\s+Mês.*?([\d\.,]+)", text))
    }

# =====================================================
# FALLBACK IA PARA GARANTIA DE 100% DOS DADOS
# =====================================================

def ai_fallback(text):
    prompt = f"""
    Extraia TODOS os dados desta fatura Copel para JSON. Não ignore nenhum campo.
    Campos Obrigatórios: 
    - identificacao (uc, numero_fatura, emissao, chave, protocolo, periodo_fiscal, vencimento, total)
    - cliente (nome, documento, endereco, cidade, estado, cep)
    - medidor (numero, leitura_anterior, leitura_atual, consumo)
    - itens_fatura (lista detalhada)
    - tributos (icms, pis, cofins com base e aliquota)
    - historico_consumo (lista de meses)
    - scee (uc_geradora, saldo_acumulado - SE EXISTIR)

    Texto: {text}
    """
    try:
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(chat.choices[0].message.content)
    except: return None

# =====================================================
# FUNÇÃO PRINCIPAL
# =====================================================

def process_copel_bill(pdf_path: Path):
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join([p.extract_text() for p in pdf.pages])
        first_page = pdf.pages[0]

    # Tentativa com Regex (Frequente e Rápido)
    resultado = {
        "arquivo": pdf_path.name,
        "identificacao": {
            "uc": safe_search(r"UNIDADE CONSUMIDORA\s+(\d+)", full_text),
            "numero_fatura": safe_search(r"N[uú]mero da fatura:\s*([\w\-]+)", full_text),
            "vencimento": safe_search(r"VENCIMENTO\s+(\d{{2}}/\d{{2}}/\d{{4}})", full_text),
            "total_a_pagar": br_val(safe_search(r"TOTAL A PAGAR\s+R?\$?\s*([\d\.,]+)", full_text)),
            "chave_acesso": safe_search(r"Chave de Acesso\s+([\d\s]+)", full_text),
            "emissao": safe_search(r"DATA DE EMISSÃO:\s*(\d{{2}}/\d{{2}}/\d{{4}})", full_text),
            "periodo_fiscal": safe_search(r"PERÍODO FISCAL:\s*(\d{{2}}/\d{{2}}/\d{{4}})", full_text)
        },
        "cliente": {
            "nome": safe_search(r"Nome:\s*(.+)", full_text),
            "documento": safe_search(r"(CPF|CNPJ):\s*([\d\.\-\/\*]+)", full_text, group=2)
        },
        "medicao": {
            "leitura_anterior": safe_search(r"Leitura anterior\s+(\d{{2}}/\d{{2}}/\d{{4}})", full_text),
            "leitura_atual": safe_search(r"Leitura atual\s+(\d{{2}}/\d{{2}}/\d{{4}})", full_text),
            "n_dias": safe_search(r"Nº de dias\s+(\d+)", full_text)
        },
        "medidor_detalhe": {
            "numero": safe_search(r"Medidor\s+(\d+)", full_text),
            "consumo_kwh": br_val(safe_search(r"CONSUMO kWh TP.*?(\d+)", full_text))
        },
        "itens_fatura": extract_items_completos(first_page),
        "tributos": extract_tributos(full_text),
        "scee": extract_scee_completo(full_text),
        "metodo": "REGEX"
    }

    # SE FALHAR DADOS CRÍTICOS (UC ou Total), CHAMA A IA
    if not resultado["identificacao"]["uc"] or resultado["identificacao"]["total_a_pagar"] == 0:
        ia_data = ai_fallback(full_text)
        if ia_data:
            ia_data["metodo"] = "GROQ_AI"
            return ia_data

    return resultado