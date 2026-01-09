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
                return self.normalize(m.group(group)) if m.group(group) else None
            except:
                return self.normalize(m.group(0))
        return None

    def extract_cliente_info(self, text):
        # Detecção de Fase (Essencial para a Taxa Mínima do seu papel)
        fase_str = self.safe_search(r"(Monofasico|Bifasico|Trifasico)\s*/\d+A", text)
        taxa_minima = 30
        if fase_str:
            if "Trifasico" in fase_str:
                taxa_minima = 100
            elif "Bifasico" in fase_str:
                taxa_minima = 50

        # Detecção de GD1 ou GD2 (Lei 14.300)
        regime = "GD1"
        if any(x in text.upper() for x in ["GD II", "GD 2", "14.300", "14300"]):
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
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text)
            }
        }

    def extract_fatura_dados(self, text):
        return {
            "mes_referencia": self.safe_search(r"(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text))
        }

    def extract_itens_faturados(self, text):
        itens = []
        # Captura: Descrição | Unid | Quant | Preço C/ Trib | Valor | PIS/COF | ICMS | Tarifa Líquida
        # O segredo está no último grupo: a tarifa sem impostos (unitária)
        pattern = r"(.*?)\s+(kWh|UN)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)"

        lines = text.split('\n')
        for line in lines:
            m = re.search(pattern, line)
            if m:
                desc = self.normalize(m.group(1))
                val_total = self.br_money_to_float(m.group(5))
                tarifa_liquida = self.br_money_to_float(m.group(8))  # A última coluna da COPEL

                tipo = "OUTROS"
                if "CONSUMO" in desc.upper():
                    tipo = "TE"
                elif "USO SISTEMA" in desc.upper():
                    tipo = "TUSD"
                elif "ILUMIN" in desc.upper():
                    tipo = "IP"
                elif "INJ" in desc.upper() or val_total < 0:
                    tipo = "CREDITO"

                itens.append({
                    "descricao": desc,
                    "tipo": tipo,
                    "quantidade": self.br_money_to_float(m.group(3)),
                    "valor_bruto": val_total,
                    "tarifa_liquida": tarifa_liquida
                })
        return itens

    def extract_historicos(self, text):
        # Pega os últimos 12 meses para o seu cálculo de média no VB6
        pattern = r"([A-Z]{3}/\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        regs = []
        for m in matches:
            regs.append({"mes": m[0], "kwh": int(m[1].replace('.', '')), "dias": int(m[2])})
        return regs