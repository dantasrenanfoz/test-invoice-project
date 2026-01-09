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
        if m:
            return self.normalize(m.group(group))
        return None

    def extract_cliente_info(self, text):
        # VOLTANDO PARA A LÓGICA DA VERSÃO 1: Busca simples por 9 dígitos
        uc = self.safe_search(r"(?:UNIDADE CONSUMIDORA|DÉBITO AUTOMÁTICO|UC)\s*[:\s]*(\d{9,10})", text) or \
             self.safe_search(r"(?:\s|^)(\d{9,10})(?:\s|$)", text)  # Busca qualquer número de 9 ou 10 dígitos solto

        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)", text)
        taxa_minima = 30
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_minima = 100
            elif "Bifasico" in fase_str:
                taxa_minima = 50

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*\n", text),
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "tipo_fase": fase_str or "Trifasico",
            "kwh_disponibilidade": taxa_minima,
            "regime_gd": "GD2" if "GD II" in text or "GD 2" in text else "GD1",
            "endereco": {
                "logradouro": self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text),
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text)
            }
        }

    def extract_fatura_dados(self, text):
        # VOLTANDO PARA A LÓGICA DA VERSÃO 1: Busca o valor próximo a "TOTAL"
        valor = self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text) or \
                self.safe_search(r"R\$\s*([\d\.,]+)", text)

        return {
            "mes_referencia": self.safe_search(r"(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(valor)
        }

    def extract_medicoes(self, text):
        registros = []
        # Mantendo a captura de medidores que já funcionava
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        matches = re.findall(pattern, text)
        for m in matches:
            registros.append({
                "medidor": m[0],
                "tipo": "CONSUMO" if "CONSUMO" in m[1] else "GERACAO",
                "leitura_atual": int(m[4].replace('.', '')),
                "valor_apurado": int(m[6].replace('.', ''))
            })
        return registros

    def extract_itens_faturados(self, text):
        itens = []
        # Captura genérica de linhas: Descrição + Unidade + Valores
        for line in text.split('\n'):
            m = re.search(r"(.*?)\s+(kWh|UN)\s+([\d\.,\s-]+)", line)
            if m:
                desc = self.normalize(m.group(1))
                nums = m.group(3).split()
                if len(nums) < 1: continue

                # Pegamos o valor da linha e a tarifa unitária (última coluna)
                valor_total = self.br_money_to_float(nums[2]) if len(nums) > 2 else self.br_money_to_float(nums[0])
                tarifa_liq = self.br_money_to_float(nums[-1])

                tipo = "OUTROS"
                if "CONSUMO" in desc.upper() and "USO" not in desc.upper():
                    tipo = "TE"
                elif "USO SISTEMA" in desc.upper() or "TUSD" in desc.upper():
                    tipo = "TUSD"
                elif "ILUMIN" in desc.upper():
                    tipo = "IP"
                elif "INJETADA" in desc.upper() or "INJ" in desc.upper() or valor_total < 0:
                    tipo = "CREDITO"

                itens.append({
                    "descricao": desc, "tipo": tipo, "quantidade": self.br_money_to_float(nums[0]),
                    "valor": valor_total, "tarifa_liquida": tarifa_liq
                })
        return itens

    def extract_scee(self, text):
        s_acum = self.safe_search(r"Saldo Acumulado.*?(\d+)", text.replace("\n", " "))
        return {"saldos": {"acumulado": {"tp": int(s_acum) if s_acum and s_acum.isdigit() else 0}}}