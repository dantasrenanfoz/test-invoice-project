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

    def safe_search(self, pattern, text, group=1):
        if not text: return None
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return self.normalize(m.group(group)) if m else None

    def extract_cliente_info(self, text):
        # UC - Busca robusta da Versão 1
        uc = self.safe_search(r"(?:UNIDADE CONSUMIDORA|UC)\s*[:\s]*(\d{9,10})", text) or \
             self.safe_search(r"(?:\s|^)(\d{9,10})(?:\s|$)", text)

        # Inteligência de Fase (Assina)
        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)", text)
        taxa_min = 30
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_min = 100
            elif "Bifasico" in fase_str:
                taxa_min = 50

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*\n", text),
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "tipo_fase": fase_str or "Trifasico",
            "kwh_disponibilidade": taxa_min,
            "regime_gd": "GD2" if "GD II" in text or "GD 2" in text else "GD1",
            "endereco": {
                "logradouro": self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text),
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text),
                "cep": self.safe_search(r"CEP:\s*(\d{5}-\d{3})", text)
            }
        }

    def extract_fatura_dados(self, text):
        # Procura o padrão de mês/ano (00/0000) mas garante que não é o CNPJ
        # buscando a palavra "REF" ou "MÊS" antes, ou validando a posição
        match = re.search(r"(?:MÊS|REF|ANO).*?(\d{2}/\d{4})", text, re.IGNORECASE | re.DOTALL)
        if match:
            mes_ref = match.group(1)
        else:
            # Tenta pegar a data de vencimento e extrair o mês anterior como fallback
            mes_ref = self.safe_search(r"(\d{2}/\d{4})", text)

        valor = self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text)

        return {
            "mes_referencia": mes_ref,
            "vencimento": self.safe_search(r"(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(valor)
        }

    def extract_medicoes(self, text):
        registros = []
        # Captura medidor, tipo, leituras e o valor apurado (kWh do mês)
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        matches = re.findall(pattern, text)
        for m in matches:
            registros.append({
                "medidor": m[0],
                "tipo": "GERACAO" if "GERAC" in m[1].upper() else "CONSUMO",
                "posto": m[2] if m[2] else "TP",
                "leitura_anterior": int(m[3].replace('.', '')),
                "leitura_atual": int(m[4].replace('.', '')),
                "constante": int(self.br_money_to_float(m[5])),
                "valor_apurado": int(m[6].replace('.', ''))
            })
        return registros

    def extract_itens_faturados(self, text):
        itens = []
        for line in text.split('\n'):
            # Captura a descrição, unidade e a sequência de valores (8 colunas)
            m = re.search(r"(.*?)\s+(kWh|UN|kW)\s+([\d\.,\s-]+)", line)
            if m:
                desc = self.normalize(m.group(1))
                nums = m.group(3).split()
                if len(nums) < 1: continue

                valor_total = self.br_money_to_float(nums[2]) if len(nums) > 2 else self.br_money_to_float(nums[0])
                tarifa_liq = self.br_money_to_float(nums[-1])

                tipo = "OUTROS"
                if "CONSUMO" in desc.upper() and "USO" not in desc.upper():
                    tipo = "TE"
                elif "USO SISTEMA" in desc.upper() or "TUSD" in desc.upper():
                    tipo = "TUSD"
                elif "ILUMIN" in desc.upper():
                    tipo = "IP"
                elif "INJETADA" in desc.upper() or "INJ" in desc.upper():
                    tipo = "INJETADA"

                itens.append({
                    "descricao": desc, "tipo": tipo, "unidade": m.group(2),
                    "quantidade": self.br_money_to_float(nums[0]),
                    "valor": valor_total, "tarifa_liquida": tarifa_liq
                })
        return itens

    def extract_historicos(self, text):
        # HISTÓRICO DE 12 MESES (Restaurado)
        pattern = r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        return [{"mes": m[0], "kwh": int(m[1].replace('.', '')), "dias": int(m[2])} for m in matches]

    def extract_scee(self, text):
        s_acum = self.safe_search(r"Saldo Acumulado.*?(\d+)", text.replace("\n", " "))
        return {"participa": "SCEE" in text or "GERAC" in text,
                "saldos": {"acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0}}}

    def extract_tributos(self, text):
        # TRIBUTOS (Restaurado)
        tribs = {}
        for t in ["ICMS", "PIS", "COFINS"]:
            m = re.search(rf"{t}\s+([\d\.,]+)\s+([\d\.,]+)%\s+([\d\.,]+)", text)
            if m: tribs[t.lower()] = {"base": self.br_money_to_float(m[1]), "valor": self.br_money_to_float(m[3])}
        return tribs