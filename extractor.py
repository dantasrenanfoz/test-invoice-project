import re


class CopelExtractor:
    @staticmethod
    def normalize(text):
        if not text: return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def br_money_to_float(v):
        if not v: return 0.0
        if isinstance(v, (int, float)): return float(v)
        # Limpa o valor para conversão (R$, pontos de milhar, vírgula decimal)
        v = v.replace("R$", "").strip().replace(".", "").replace(",", ".")
        try:
            return float(v)
        except:
            return 0.0

    @staticmethod
    def safe_search(pattern, text, group=1, flags=re.IGNORECASE | re.DOTALL):
        if not text: return None
        m = re.search(pattern, text, flags)
        if m:
            if group <= len(m.groups()):
                val = m.group(group)
            else:
                val = m.group(0)
            return re.sub(r"\s+", " ", val).strip() if val else None
        return None

    def extract_itens_financeiros(self, text):
        itens = []
        # NOVA ESTRATÉGIA: Ancoragem na Unidade
        # Procuramos por: Unidade + Valor1 + Valor2 + Valor3
        # Ex: "kWh 698 0,375129 261,84"
        pattern_valores = r"\s+(kWh|UN|kW|kVArh)\s+(-?[\d\.,]+)\s+([\d\.,]+)\s+(-?[\d\.,]+)"

        for line in text.split('\n'):
            line = line.strip()
            # Ignora linhas de cabeçalho
            if "Preço unit" in line or "TOTAL" in line: continue

            m = re.search(pattern_valores, line)
            if m:
                # A descrição é tudo o que está antes da unidade na linha
                desc_raw = line[:m.start()].strip()
                desc = self.normalize(desc_raw)

                # Filtro de palavras-chave para validar se é um item da conta
                keywords = ["ENERGIA", "TUSD", "TE", "INJ", "CONT", "ILUM", "USO", "GD", "MULTA", "JUROS", "ADICIONAL"]
                if any(k in desc.upper() for k in keywords):
                    itens.append({
                        "descricao": desc,
                        "unid": m.group(1),
                        "quant": self.br_money_to_float(m.group(2)),
                        "preco_unit": self.br_money_to_float(m.group(3)),
                        "valor_total": self.br_money_to_float(m.group(4))
                    })
        return itens

    def extract_scee(self, text):
        """Busca saldos de GD ignorando ruídos técnicos"""
        if "SCEE" not in text and "Saldo" not in text:
            return {"possui_gd": False}

        # O Saldo 728: Procuramos o número que vem após 'Acumulado' e o texto técnico
        # Usamos \b para garantir que pegamos o número inteiro isolado
        saldo_acum = self.safe_search(r"Saldo\s+Acumulado.*?\s+(\d+)\b", text)
        saldo_mes = self.safe_search(r"Saldo\s+M[eê]s.*?\s+(\d+)\b", text)
        uc_geradora = self.safe_search(r"Geradora:\s*UC\s*(\d+)", text)

        return {
            "possui_gd": True,
            "uc_geradora": uc_geradora,
            "saldo_mes_atual": int(saldo_mes) if saldo_mes else 0,
            "saldo_acumulado_total": int(saldo_acum) if saldo_acum else 0,
            "modalidade": "SCEE - Sistema de Compensação de Energia"
        }

    def extract_medicao(self, text):
        # Medidor | CONSUMO kWh | Anterior | Atual | Const | Consumo
        pattern = r"(\d{8,})\s+CONSUMO\s+kWh\s+.*?([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        m = re.search(pattern, text)

        # Dias de faturamento: Busca no quadro lateral (Ex: OUT25 698 30)
        dias_match = re.search(r"[A-Z]{3}\d{2}\s+[\d\.]+\s+(\d{1,2})", text)
        dias = dias_match.group(1) if dias_match else self.safe_search(r"N[ºo].\s*de\s*dias\s*(\d+)", text)

        if m:
            return {
                "numero_medidor": m.group(1),
                "leitura_anterior": int(m.group(2).replace('.', '')),
                "leitura_atual": int(m.group(3).replace('.', '')),
                "constante": int(m.group(4)),
                "consumo_mes_kwh": int(m.group(5).replace('.', '')),
                "dias_faturamento": int(dias) if dias else None
            }
        return None

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

    def extract_historico(self, text):
        pattern = r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, text)
        hist = []
        for m in matches:
            if m[0] in ["CEP", "CNP"]: continue
            hist.append({
                "mes": m[0],
                "kwh": int(m[1].replace('.', '')),
                "dias": int(m[2])
            })
        return hist