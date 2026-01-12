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
        # 1. Busca UC ignorando números fixos da COPEL (Insc. Estadual e CNPJ)
        # O findall vai listar todos os números de 8 a 10 dígitos encontrados
        todos_numeros = re.findall(r"(?:\s|^)(\d{8,10})(?:\s|$)", text)

        uc = None
        for candidato in todos_numeros:
            # Lista de exclusão:
            # 9023307399 (Insc. Estadual Copel)
            # 04368898000106 (CNPJ Copel)
            if candidato not in ["9023307399", "04368898000106", "04368898"]:
                # UC da Copel geralmente tem 8 ou 9 dígitos
                if 8 <= len(candidato) <= 9:
                    uc = candidato
                    break

        # Fallback caso não ache pelo loop: tenta buscar pela palavra-chave no texto
        if not uc:
            uc = self.safe_search(r"UNIDADE CONSUMIDORA\s*[:\s]*(\d{8,9})", text)

        # 2. Inteligência de Fase (Assina)
        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)", text)
        taxa_min = 100
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_min = 100
            elif "Bifasico" in fase_str:
                taxa_min = 50
            elif "Monofasico" in fase_str:
                taxa_min = 30

        # 3. Captura e Limpeza de Endereço
        logradouro = self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text)
        if logradouro and uc:
            logradouro = logradouro.replace(uc, "").replace("  ", " ").strip()

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*\n", text),
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "tipo_fase": fase_str or "Trifasico",
            "kwh_disponibilidade": taxa_min,
            "regime_gd": "GD2" if any(x in text.upper() for x in ["GD II", "GD 2", "14.300"]) else "GD1",
            "endereco": {
                "logradouro": logradouro,
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text),
                "cep": self.safe_search(r"CEP:\s*(\d{5}-\d{3})", text)
            }
        }

    def extract_fatura_dados(self, text):
        # Captura bloco de datas (Anterior | Atual | Dias | Próxima)
        pattern_datas = r"(\d{2}/\d{2}/\d{4})[\s\n]+(\d{2}/\d{2}/\d{4})[\s\n]+(\d+)[\s\n]+(\d{2}/\d{2}/\d{4})"
        datas = re.search(pattern_datas, text)

        # Captura Mês Ref, Vencimento e Total
        pattern_fin = r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$\s*([\d\.,]+)"
        fin = re.search(pattern_fin, text)

        return {
            "mes_referencia": fin.group(1) if fin else self.safe_search(r"REF:.*?(\d{2}/\d{4})", text),
            "vencimento": fin.group(2) if fin else self.safe_search(r"VENCIMENTO\s*(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(fin.group(3)) if fin else 0,
            "data_leitura_anterior": datas.group(1) if datas else None,
            "data_leitura_atual": datas.group(2) if datas else None,
            "dias_faturamento": datas.group(3) if datas else None,
            "data_proxima_leitura": datas.group(4) if datas else None
        }

    def extract_medicoes(self, text):
        registros = []
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        matches = re.findall(pattern, text)
        for m in matches:
            registros.append({
                "medidor": m[0],
                "tipo": "GERACAO" if "GERAC" in m[1].upper() else "CONSUMO",
                "leitura_anterior": int(m[3].replace('.', '')),
                "leitura_atual": int(m[4].replace('.', '')),
                "constante": int(self.br_money_to_float(m[5])),
                "valor_apurado": int(m[6].replace('.', ''))
            })
        return registros

    def extract_itens_faturados(self, text):
        itens = []
        for line in text.split('\n'):
            m = re.search(r"(.*?)\s+(kWh|UN|kW)\s+([\d\.,\s-]+)", line)
            if m:
                desc = self.normalize(m.group(1))
                nums = m.group(3).split()
                if len(nums) < 1: continue

                valor_total = self.br_money_to_float(nums[2]) if len(nums) > 2 else self.br_money_to_float(nums[0])
                tarifa_liq = self.br_money_to_float(nums[-1])

                tipo = "OUTROS"
                # TE e TUSD apenas para consumo positivo
                if "CONSUMO" in desc.upper() and "USO" not in desc.upper() and valor_total > 0:
                    tipo = "TE"
                elif ("USO SISTEMA" in desc.upper() or "TUSD" in desc.upper()) and valor_total > 0:
                    tipo = "TUSD"
                elif "ILUMIN" in desc.upper():
                    tipo = "IP"
                elif any(x in desc.upper() for x in ["INJETADA", "INJ", "COMPENSADA"]):
                    tipo = "INJETADA"

                itens.append({
                    "descricao": desc, "tipo": tipo, "unidade": m.group(2),
                    "quantidade": abs(self.br_money_to_float(nums[0])),
                    "valor": valor_total, "tarifa_liquida": tarifa_liq
                })
        return itens

    def extract_historicos(self, text):
        pattern = r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        return [{"mes": m[0], "kwh": int(m[1].replace('.', '')), "dias": int(m[2])} for m in matches]

    def extract_scee(self, text):
        s_acum = self.safe_search(r"Saldo Acumulado.*?(\d+)", text.replace("\n", " "))
        return {"participa": "SCEE" in text or "GERAC" in text,
                "saldos": {"acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0}}}

    def extract_tributos(self, text):
        tribs = {}
        for t in ["ICMS", "PIS", "COFINS"]:
            m = re.search(rf"{t}\s+([\d\.,]+)\s+[\d\.,]+%\s+([\d\.,]+)", text)
            if m: tribs[t.lower()] = {"base": self.br_money_to_float(m[1]), "valor": self.br_money_to_float(m[2])}
        return tribs