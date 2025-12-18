import pdfplumber
import re
import json
from pathlib import Path


# ===============================
# 1. UTILIDADES & CONVERSORES
# ===============================

def normalize(text: str) -> str:
    """Remove espaços extras e quebras de linha desnecessárias."""
    if not text: return ""
    return re.sub(r"\s+", " ", text).strip()


def br_money_to_float(v):
    """Converte R$ 1.234,56 ou 1.234,56 para float 1234.56"""
    if not v: return None
    if isinstance(v, (float, int)): return float(v)

    # Remove R$, espaços e pontos de milhar
    clean = v.replace("R$", "").replace(" ", "").replace(".", "")
    # Troca vírgula decimal por ponto
    clean = clean.replace(",", ".")

    try:
        return float(clean)
    except ValueError:
        return None


def find_value_near_anchor(words, anchor_text, search_type="below", tolerance_x=15, tolerance_y=35):
    """
    Estratégia Espacial: Encontra um valor baseando-se na posição de uma palavra âncora.

    Args:
        words: Lista de palavras do pdfplumber (page.extract_words())
        anchor_text: Texto para procurar (ex: "VENCIMENTO")
        search_type: "below" (valor está abaixo) ou "right" (valor está à direita)
        tolerance_x: Desvio horizontal aceitável
        tolerance_y: Desvio vertical aceitável (altura da linha)
    """
    anchor = None
    # 1. Encontrar a âncora
    for w in words:
        # Normaliza para maiúsculo e remove acentos básicos para comparação segura
        w_text = w['text'].upper().replace("Ê", "E").replace("Ç", "C").replace("Ã", "A")
        tgt_text = anchor_text.upper().replace("Ê", "E").replace("Ç", "C").replace("Ã", "A")

        if tgt_text in w_text:
            anchor = w
            break

    if not anchor:
        return None

    candidates = []

    # 2. Procurar candidatos na zona de busca
    for w in words:
        if w == anchor: continue
        if w['text'] in ["R$", "RS"]: continue  # Ignora símbolo de moeda solto

        if search_type == "below":
            # O candidato deve estar abaixo da âncora (top > anchor.bottom)
            # Mas não muito longe (dentro da tolerancia Y)
            # E alinhado horizontalmente (dentro da tolerancia X)
            is_below = anchor['bottom'] <= w['top'] <= anchor['bottom'] + tolerance_y
            is_aligned = (anchor['x0'] - tolerance_x) <= w['x0'] <= (anchor['x1'] + tolerance_x)

            if is_below and is_aligned:
                candidates.append(w)

        elif search_type == "right":
            # O candidato deve estar à direita (x0 > anchor.x1)
            # Na mesma linha visual
            is_same_line = abs(w['top'] - anchor['top']) < 5
            is_right = w['x0'] >= anchor['x1']

            if is_same_line and is_right:
                candidates.append(w)

    if not candidates:
        return None

    # 3. Retornar o melhor candidato
    if search_type == "below":
        # Pega o que estiver visualmente mais acima (mais próximo da âncora)
        return sorted(candidates, key=lambda x: x['top'])[0]['text']
    else:
        # Pega o que estiver mais à esquerda (mais próximo da âncora)
        return sorted(candidates, key=lambda x: x['x0'])[0]['text']


# ===============================
# 2. EXTRAÇÃO DE TABELAS (ITENS)
# ===============================

def extract_itens_fatura(page):
    itens = []

    # ESTRATÉGIA: Recorte Largo
    # Em vez de tentar acertar a altura exata, pegamos do meio até o fim da página
    # O Regex vai filtrar o que é lixo.
    width = page.width
    height = page.height

    # Começa em 300 (pula cabeçalho) e vai até 750 (antes do rodapé final)
    bbox = (0, 300, width, 750)

    try:
        crop = page.crop(bbox)
        text = crop.extract_text() or ""
    except:
        # Fallback se o crop falhar (página muito pequena)
        text = page.extract_text() or ""

    lines = text.split("\n")

    for line in lines:
        line = normalize(line)

        # REGEX AJUSTADO PARA COPEL NF3e:
        # 1. (.+?) -> Pega qualquer descrição (letras, numeros, pontos)
        # 2. (kWh|UN) -> Unidade
        # 3. ([\d\.,]+) -> Quantidade (aceita decimais)
        # ... Valores monetários
        pattern = r"(.+?)\s+(kWh|UN)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)"

        m = re.match(pattern, line, re.IGNORECASE)
        if m:
            descricao = m.group(1).strip()

            # Filtra cabeçalhos da tabela que possam ter casado com o regex
            if "ITENS" in descricao.upper() or "TRIBUTO" in descricao.upper():
                continue

            itens.append({
                "descricao": descricao,
                "unidade": m.group(2),
                "quantidade": br_money_to_float(m.group(3)),
                "valor_unitario": br_money_to_float(m.group(4)),
                "valor_total": br_money_to_float(m.group(5))
            })

    return itens


def extract_historico(text):
    """Extrai histórico de consumo via Regex no texto completo (Metodo Robustro)"""
    hist = []
    # Padrão: MÊSANO (3 letras + 2 digitos) + Consumo + Dias
    # Ex: OUT25 698 30
    pattern = r"([A-Z]{3}\d{2})\s+(\d+)\s+(\d{1,2})"

    for m in re.finditer(pattern, text):
        mes_raw = m.group(1)
        kwh = int(m.group(2))
        dias = int(m.group(3))

        # Converte JAN25 para 01/2025
        meses_map = {
            "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04", "MAI": "05", "JUN": "06",
            "JUL": "07", "AGO": "08", "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12"
        }
        mes_nome = mes_raw[:3]
        ano_abrev = mes_raw[3:]
        mes_fmt = f"{meses_map.get(mes_nome, '00')}/20{ano_abrev}"

        hist.append({
            "mes": mes_fmt,
            "kwh": kwh,
            "dias": dias
        })

    # Remove duplicatas preservando ordem
    uniq = []
    seen = set()
    for h in hist:
        k = (h['mes'], h['kwh'])
        if k not in seen:
            seen.add(k)
            uniq.append(h)

    return uniq


# ===============================
# 3. EXTRAÇÃO PRINCIPAL
# ===============================

def process_copel_bill(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        words = page.extract_words()  # Vital para a estratégia de âncoras

        # --- ESTRATÉGIA HÍBRIDA ---

        # 1. ÂNCORAS (Para campos flutuantes)
        # Procuramos o rótulo e pegamos o valor imediatamente ABAIXO ou ao LADO

        uc = find_value_near_anchor(words, "CONSUMIDORA", "below", tolerance_y=50)
        # Fallback para UC: Às vezes o OCR junta "CONSUMIDORA" e o número
        if not uc:
            m_uc = re.search(r"CONSUMIDORA\s*(\d+)", text)
            if m_uc: uc = m_uc.group(1)

        mes_ref = find_value_near_anchor(words, "MÊS/ANO", "below", tolerance_y=30)
        vencimento = find_value_near_anchor(words, "VENCIMENTO", "below", tolerance_y=30)

        # Para o Total, a âncora "PAGAR" é mais segura que "TOTAL" (que aparece em várias tabelas)
        total_pagar_raw = find_value_near_anchor(words, "PAGAR", "below", tolerance_y=30)

        # 2. REGEX DE TEXTO (Para campos padronizados)

        # Endereço: Pega tudo entre "Endereço:" e o próximo label forte
        endereco_match = re.search(r"Endereço:\s*(.*?)\s*(Cidade:|CEP:|CPF:)", text, re.DOTALL | re.IGNORECASE)
        endereco_full = normalize(endereco_match.group(1)) if endereco_match else None

        # CPF Mascarado
        cpf_match = re.search(r"CPF:\s*([0-9\.\-*\s]+)", text)
        cpf = normalize(cpf_match.group(1)) if cpf_match else None

        nome_match = re.search(r"Nome:\s*([^\n]+)", text)
        nome = normalize(nome_match.group(1)) if nome_match else None

        # 3. ITENS E HISTÓRICO
        itens = extract_itens_fatura(page)
        historico = extract_historico(text)

        # 4. IMPOSTOS (Lógica simples de Regex no texto corrido)
        icms_val = re.search(r"ICMS.*?\s+([\d,]+)$", text, re.MULTILINE)
        icms_base = re.search(r"ICMS.*?\s+([\d,]+)\s+[\d,]+%", text, re.MULTILINE)

        # Montagem do JSON Final
        data = {
            "status": "ok",
            "mensagem": "Extração realizada com sucesso.",
            "dados_extraidos": {
                "concessionaria": {
                    "nome": "COPEL DISTRIBUIÇÃO S.A.",
                    "cnpj": "04.368.898/0001-06",  # Estático para Copel
                    "inscricao_estadual": "9023307399",
                    "site": "www.copel.com"
                },
                "cliente": {
                    "nome": nome,
                    "cpf": cpf,
                    "endereco": {
                        "logradouro_completo": endereco_full,  # Simplificado para evitar erros de split
                    }
                },
                "contrato": {
                    "unidade_consumidora": normalize(uc),
                    "subgrupo": "B1" if "B1" in text else "A4",  # Inferência simples
                    "tipo_fornecimento": {
                        "fases": "tri" if "trifasico" in text.lower() else (
                            "mono" if "monofasico" in text.lower() else "bi")
                    }
                },
                "referencia_fatura": {
                    "mes_referencia": mes_ref,
                    "vencimento": vencimento,
                    "total_pagar": br_money_to_float(total_pagar_raw)
                },
                "itens_fatura": itens,
                "historico_consumo": historico,
                "impostos": {
                    "icms": {
                        "valor": br_money_to_float(icms_val.group(1)) if icms_val else 0.0,
                        # Tenta pegar base de calculo se achar, senão 0
                        "base_calculo": br_money_to_float(icms_base.group(1)) if icms_base else 0.0
                    }
                }
            }
        }

        return data


# ===============================
# EXECUÇÃO
# ===============================
if __name__ == "__main__":
    arquivo_pdf = "copel700_unlocked.pdf"  # Nome do seu arquivo

    if Path(arquivo_pdf).exists():
        resultado = process_copel_bill(arquivo_pdf)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    else:
        print(f"Arquivo {arquivo_pdf} não encontrado.")