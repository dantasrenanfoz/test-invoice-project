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
                res = m.group(group)
                return self.normalize(res) if res else None
            except:
                return self.normalize(m.group(0))
        return None

    def extract_cliente_info(self, text):
        # --- NOVA DETECÇÃO: FASE E TAXA MÍNIMA ---
        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)\s*/\d+A", text)
        taxa_minima = 30
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_minima = 100
            elif "Bifasico" in fase_str:
                taxa_minima = 50

        # --- NOVA DETECÇÃO: GD1 OU GD2 ---
        regime = "GD1"
        if any(x in text.upper() for x in ["GD II", "GD 2", "14.300", "LEI 14300"]):
            regime = "GD2"

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*(?:Endereço|Enderezo|CNPJ|CPF)", text),
            "uc": self.safe_search(r"UNIDADE CONSUMIDORA\s+(\d{8,10})", text) or self.safe_search(
                r"(\d{8,10})\s+CÓDIGO DÉBITO", text),
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "tipo_fase": fase_str,
            "kwh_disponibilidade": taxa_minima,
            "regime_gd": regime,
            "endereco": {
                "logradouro": self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text),
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text),
                "cep": self.safe_search(r"CEP:\s*(\d{5}-\d{3})", text)
            }
        }

    def extract_fatura_dados(self, text):
        return {
            "mes_referencia": self.safe_search(r"REF\.\s*M[EÊ]S.*?(\d{2}/\d{4})", text) or self.safe_search(
                r"(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"VENCIMENTO\s*(\d{2}/\d{2}/\d{4})", text) or self.safe_search(
                r"(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text))
        }

    def extract_medicoes(self, text):
        registros = []
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        matches = re.findall(pattern, text)
        for m in matches:
            registros.append({
                "medidor": m[0],
                "tipo": "CONSUMO" if "CONSUMO" in m[1] else "GERACAO",
                "posto": m[2] if m[2] else "TP",
                "leitura_anterior": int(m[3].replace('.', '')),
                "leitura_atual": int(m[4].replace('.', '')),
                "constante": int(self.br_money_to_float(m[5])),
                "valor_apurado": int(m[6].replace('.', ''))
            })
        return registros

    def extract_itens_faturados(self, text):
        itens = []
        # Captura as 8 colunas da Copel, incluindo a última (Tarifa Líquida sem impostos)
        pattern = r"(.*?)\s+(kWh|UN|kW|kVArh)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)"
        for line in text.split('\n'):
            m = re.search(pattern, line)
            if m:
                desc = self.normalize(m.group(1))
                val_total = self.br_money_to_float(m.group(5))
                tarifa_liq = self.br_money_to_float(m.group(8))  # Coluna Tarifa unit. (R$)

                tipo = "OUTROS"
                if "CONSUMO" in desc.upper():
                    tipo = "TE"
                elif "USO SISTEMA" in desc.upper() or "TUSD" in desc.upper():
                    tipo = "TUSD"
                elif "ILUMINACAO" in desc.upper() or "ILUMIN PUBLICA" in desc.upper():
                    tipo = "IP"
                elif "INJ" in desc.upper() or val_total < 0:
                    tipo = "CREDITO"

                itens.append({
                    "descricao": desc, "tipo": tipo, "unidade": m.group(2),
                    "quantidade": self.br_money_to_float(m.group(3)),
                    "preco_com_tributo": self.br_money_to_float(m.group(4)),
                    "valor": val_total,
                    "tarifa_liquida": tarifa_liq
                })
        return itens

    def extract_scee(self, text):
        s_acum = self.safe_search(r"Saldo\s+Acumulado.*?\b(\d+)\b", text)
        return {
            "participa": "Demonstrativo" in text or "SCEE" in text,
            "saldos": {"acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0}}
        }

    def extract_historicos(self, text):
        pattern = r"([A-Z]{3})(\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        registros = []
        for m in matches:
            registros.append({"mes": f"{m[0]}{m[1]}", "kwh": int(m[2].replace('.', '')), "dias": int(m[3])})
        return registros

    def extract_tributos(self, text):
        tribs = {}
        for t in ["ICMS", "PIS", "COFINS"]:
            m = re.search(rf"{t}\s+([\d\.,]+)\s+([\d\.,]+)%\s+([\d\.,]+)", text)
            if m: tribs[t.lower()] = {"base": self.br_money_to_float(m[1]), "valor": self.br_money_to_float(m[3])}
        return tribs