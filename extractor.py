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
        # Captura da UC - Refinada para ignorar falsos positivos
        uc = self.safe_search(r"UNIDADE CONSUMIDORA\s*\n?\s*(\d{8,10})", text) or \
             self.safe_search(r"(\d{9,10})\s*CÓDIGO DÉBITO", text)

        # Fase e Taxa
        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)\s*/\d+A", text)
        taxa_minima = 30
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_minima = 100
            elif "Bifasico" in fase_str:
                taxa_minima = 50

        regime = "GD1"
        if any(x in text.upper() for x in ["GD II", "GD 2", "14.300", "LEI 14300"]):
            regime = "GD2"

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*\n", text),
            "uc": uc,
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
        # Procura especificamente o bloco REF / VENCIMENTO / TOTAL
        # Evita pegar o 0001/06 do CNPJ da Copel
        bloco_financeiro = self.safe_search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$\s*([\d\.,]+)", text, group=0)

        if bloco_financeiro:
            partes = bloco_financeiro.split()
            return {
                "mes_referencia": partes[0],
                "vencimento": partes[1],
                "valor_total": self.br_money_to_float(partes[2])
            }

        return {
            "mes_referencia": self.safe_search(r"REF: MÊS / ANO\s*\n?\s*(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"VENCIMENTO\s*\n?\s*(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(self.safe_search(r"TOTAL A PAGAR\s*\n?\s*R\$\s*([\d\.,]+)", text))
        }

    def extract_medicoes(self, text):
        registros = []
        # Regex ajustada para capturar o Consumo e a Geração (como na conta do Consórcio)
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
        # Captura ampliada para pegar as 8 colunas e identificar IP corretamente
        pattern = r"(.*?)\s+(kWh|UN|kW|kVArh)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)"
        lines = text.split('\n')
        for line in lines:
            m = re.search(pattern, line)
            if m:
                desc = self.normalize(m.group(1))
                val_total = self.br_money_to_float(m.group(5))
                tarifa_liq = self.br_money_to_float(m.group(8))

                tipo = "OUTROS"
                if "CONSUMO" in desc.upper():
                    tipo = "TE"
                elif "USO SISTEMA" in desc.upper() or "TUSD" in desc.upper():
                    tipo = "TUSD"
                elif "ILUMIN" in desc.upper() or "CONT ILUM" in desc.upper():
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
        # Saldo Acumulado (Para o Consórcio)
        s_acum = self.safe_search(r"Saldo Acumulado.*?(\d+)", text)
        return {
            "participa": "Demonstrativo" in text or "SCEE" in text or "GERAC" in text,
            "saldos": {"acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0}}
        }

    def extract_historicos(self, text):
        # Histórico de Consumo
        pattern = r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        registros = []
        for m in matches:
            registros.append({"mes": m[0], "kwh": int(m[1].replace('.', '')), "dias": int(m[2])})
        return registros

    def extract_tributos(self, text):
        tribs = {}
        for t in ["ICMS", "PIS", "COFINS"]:
            m = re.search(rf"{t}\s+([\d\.,]+)\s+([\d\.,]+)%\s+([\d\.,]+)", text)
            if m: tribs[t.lower()] = {"base": self.br_money_to_float(m[1]), "valor": self.br_money_to_float(m[3])}
        return tribs