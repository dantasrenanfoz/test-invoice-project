import re


class CopelExtractor:
    def __init__(self):
        pass

    def normalize(self, text):
        if not text: return ""
        return re.sub(r"\s+", " ", text).strip()

    def br_money_to_float(self, v):
        if not v: return 0.0
        v = str(v).replace("R$", "").strip().replace(".", "").replace(",", ".")
        try:
            return float(v)
        except:
            return 0.0

    def safe_search(self, pattern, text, group=1, flags=re.IGNORECASE | re.DOTALL):
        if not text: return None
        m = re.search(pattern, text, flags)
        if m:
            try:
                if group <= len(m.groups()):
                    res = m.group(group)
                else:
                    res = m.group(0)
                return self.normalize(res) if res else None
            except:
                return self.normalize(m.group(0))
        return None

    def extract_cliente_info(self, text):
        nome = self.safe_search(r"Nome:\s*(.*?)\s*(?:Endereço|Enderezo|CNPJ|CPF)", text)
        uc = self.safe_search(r"(\d{8,10})\s+CÓDIGO DÉBITO AUTOMÁTICO", text) or \
             self.safe_search(r"UNIDADE CONSUMIDORA\s+(\d{8,10})", text) or \
             self.safe_search(r"(?:\n|^)(\d{8,10})(?:\n|$)", text)
        end_raw = self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text) or \
                  self.safe_search(r"Enderezo:\s*(.*?)\s*CEP", text)

        if end_raw:
            match_uc_vazada = re.search(r"(\d{8,10})", end_raw)
            if match_uc_vazada:
                val = match_uc_vazada.group(1)
                if not uc: uc = val
                end_raw = end_raw.replace(val, "").replace(" - ", " ").strip()
                end_raw = re.sub(r"\s+", " ", end_raw)

        return {
            "nome": nome, "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "endereco": {
                "logradouro": end_raw,
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text),
                "cep": self.safe_search(r"CEP:\s*(\d{5}-\d{3})", text)
            }
        }

    def extract_fatura_dados(self, text):
        bloco = self.safe_search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$\s*([\d\.,]+)", text, group=0)
        if bloco:
            p = bloco.split()
            return {"mes_referencia": p[0], "vencimento": p[1], "valor_total": self.br_money_to_float(p[2])}
        return {
            "mes_referencia": self.safe_search(r"REF\.\s*M[EÊ]S.*?(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"VENCIMENTO\s*(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text))
        }

    def extract_leitura_status(self, text):
        status_raw = self.safe_search(r"(LEITURA\s+NAO\s+FORNECIDA.*?PLURIMENSAL|FATURADO:\s*MEDIA)", text)
        if status_raw:
            return {"tipo": "ESTIMADA", "motivo": "LMR" if "LMR" in status_raw else "MEDIA", "descricao": status_raw,
                    "impacta_simulacao": True}
        return {"tipo": "REAL", "motivo": "NORMAL", "impacta_simulacao": False, "descricao": "Leitura Real"}

    def extract_medicoes(self, text):
        registros = []
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        matches = re.findall(pattern, text)
        for m in matches:
            registros.append({
                "medidor": m[0],
                "tipo": "CONSUMO" if "CONSUMO" in m[1] else "GERACAO",
                "posto": m[2] if m[2] else "TP",
                "unidade": "kWh",
                "leitura_anterior": int(m[3].replace('.', '')),
                "leitura_atual": int(m[4].replace('.', '')),
                "constante": int(self.br_money_to_float(m[5])),
                "valor_apurado": int(m[6].replace('.', ''))
            })
        return registros

    def extract_itens_faturados(self, text):
        itens = []
        pattern = r"(.*?)\s+(kWh|UN|kW|kVArh)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+(-?[\d\.,]+)"
        for line in text.split('\n'):
            m = re.search(pattern, line)
            if m:
                desc = self.normalize(m.group(1))
                if any(k in desc.upper() for k in ["ENERGIA", "TUSD", "TE", "INJ", "CONT", "ILUM", "BAND"]):
                    val = self.br_money_to_float(m.group(5))
                    tipo = "CONSUMO"
                    if "INJ" in desc.upper() or val < 0:
                        tipo = "INJETADA"
                    elif "USO SISTEMA" in desc.upper() or "TUSD" in desc.upper():
                        tipo = "USO_SISTEMA"
                    elif "ILUMINACAO" in desc.upper():
                        tipo = "ILUMINACAO"
                    elif "BAND" in desc.upper():
                        tipo = "BANDEIRA"
                    itens.append({
                        "descricao": desc, "tipo": tipo, "unidade": m.group(2),
                        "quantidade": self.br_money_to_float(m.group(3)),
                        "tarifa_unitaria": self.br_money_to_float(m.group(4)),
                        "valor": val
                    })
        return itens

    def extract_scee(self, text):
        is_usina = any(x in text for x in ["Micro/Minigeradora", "Geracao de Energia Eletrica", "GERAC kWh"])
        bloco = self.safe_search(r"Demonstrativo de saldos SCEE.*?(?=A qualquer tempo|Periodos Band|$)", text, group=0)
        alvo = bloco if bloco else text
        if not bloco and not is_usina: return {"participa": False}

        s_acum = self.safe_search(r"Saldo\s+Acumulado.*?\b(\d+)\b", alvo)
        s_mes = self.safe_search(r"Saldo\s+M[eê]s.*?\b(\d+)\b", alvo)
        s_exp = self.safe_search(r"Saldo\s+a\s+Expirar.*?\b(\d+)\b", alvo)

        return {
            "participa": True, "tipo": "MICROGERADORA" if is_usina else "BENEFICIARIA",
            "saldos": {
                "mes": {"tp": int(s_mes) if s_mes and s_mes.isdigit() else 0},
                "acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0},
                "a_expirar_proximo_mes": {"tp": int(s_exp) if s_exp and s_exp.isdigit() else 0}
            }
        }

    def extract_historicos(self, text):
        bloco = self.safe_search(r"HISTÓRICO\s+DE\s+CONSUMO.*?kWh(.*?)(?:TOTAL|MEDIDOR|Reservado)", text)
        if not bloco: return {"consumo": {"registros": []}}
        pattern = r"([A-Z]{3})(\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, bloco)
        registros = []
        for m in matches:
            registros.append({
                "mes": f"{m[0]}{m[1]}", "ano": 2000 + int(m[1]),
                "kwh": int(m[2].replace('.', '')), "dias": int(m[3])
            })
        return {"consumo": {"unidade": "kWh", "registros": registros}}

    def extract_tributos(self, text):
        tributos = {}
        for trib in ["ICMS", "PIS", "COFINS"]:
            pattern = rf"{trib}\s+([\d\.,]+)\s+([\d\.,]+)%\s+([\d\.,]+)"
            m = re.search(pattern, text)
            if m:
                tributos[trib.lower()] = {
                    "base": self.br_money_to_float(m.group(1)),
                    "aliquota": self.br_money_to_float(m.group(2)),
                    "valor": self.br_money_to_float(m.group(3))
                }
        return tributos

    def extract_bandeiras(self, text):
        bandeiras = []
        pattern = r"(Vermelha|Amarela|Verde)\s*P?\d?:\s*(\d{2}/\d{2})-(\d{2}/\d{2})"
        matches = re.findall(pattern, text)
        for m in matches:
            bandeiras.append({"tipo": m[0].upper(), "inicio": m[1], "fim": m[2]})
        return bandeiras