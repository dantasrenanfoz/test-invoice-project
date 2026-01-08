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
                # Blindagem: se o grupo solicitado não existir, retorna o match completo (grupo 0)
                if group <= len(m.groups()):
                    res = m.group(group)
                else:
                    res = m.group(0)
                return self.normalize(res) if res else None
            except:
                return self.normalize(m.group(0))
        return None

    def extract_cliente_info(self, text):
        """Extrai Nome, UC e Endereço lidando com layouts de colunas"""
        # Busca Nome
        nome = self.safe_search(r"Nome:\s*(.*?)\s*(?:Endereço|Enderezo|CNPJ|CPF)", text)

        # Busca UC (Número de 8-10 dígitos próximo a labels de débito ou unidade)
        uc = self.safe_search(r"(\d{8,10})\s+CÓDIGO DÉBITO AUTOMÁTICO", text) or \
             self.safe_search(r"UNIDADE CONSUMIDORA\s+(\d{8,10})", text) or \
             self.safe_search(r"(?:\n|^)(\d{8,10})(?:\n|$)", text)

        # Busca Endereço
        end_raw = self.safe_search(r"Endereço:\s*(.*?)\s*CEP", text) or \
                  self.safe_search(r"Enderezo:\s*(.*?)\s*CEP", text)

        # TRATAMENTO PARA LAYOUT DE COLUNA: Se a UC 'vazou' para o endereço
        if end_raw:
            match_uc_dentro = re.search(r"(\d{8,10})", end_raw)
            if match_uc_dentro:
                valor_uc_vazado = match_uc_dentro.group(1)
                if not uc: uc = valor_uc_vazado
                # Limpa o endereço removendo o número da UC que "colou" ali
                end_raw = end_raw.replace(valor_uc_vazado, "").replace(" - ", " ").strip()
                end_raw = re.sub(r"\s+", " ", end_raw)

        return {
            "nome": nome,
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", text),
            "endereco": {
                "logradouro": end_raw,
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", text),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", text),
                "cep": self.safe_search(r"CEP:\s*(\d{5}-\d{3})", text)
            }
        }

    def extract_fatura_dados(self, text):
        """Captura Bloco Financeiro (Mês, Vencimento, Valor)"""
        # Tenta o padrão de linha única gerado pelo OCR/PDF: "12/2025 25/12/2025 R$75,22"
        bloco = self.safe_search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$\s*([\d\.,]+)", text, group=0)
        if bloco:
            partes = bloco.split()
            return {
                "mes_referencia": partes[0],
                "vencimento": partes[1],
                "valor_total": self.br_money_to_float(partes[2])
            }
        return {
            "mes_referencia": self.safe_search(r"REF\.\s*M[EÊ]S.*?(\d{2}/\d{4})", text),
            "vencimento": self.safe_search(r"VENCIMENTO\s*(\d{2}/\d{2}/\d{4})", text),
            "valor_total": self.br_money_to_float(self.safe_search(r"TOTAL\s+A\s+PAGAR\s+R\$\s*([\d\.,]+)", text))
        }

    def extract_leitura_status(self, text):
        """Analisa se a leitura foi real ou estimada (LMR)"""
        status_text = self.safe_search(r"(LEITURA\s+NAO\s+FORNECIDA.*?PLURIMENSAL|FATURADO:\s*MEDIA)", text)
        if status_text:
            return {
                "tipo": "ESTIMADA",
                "motivo": "LMR" if "LMR" in status_text else "MEDIA",
                "descricao": status_text,
                "impacta_simulacao": True
            }
        return {"tipo": "REAL", "motivo": "NORMAL", "descricao": "Leitura Real", "impacta_simulacao": False}

    def extract_medicoes(self, text):
        """Tabela de Medidores (Consumo e Geração)"""
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
        """Detalhamento financeiro da fatura"""
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
                        "descricao": desc,
                        "tipo": tipo,
                        "unidade": m.group(2),
                        "quantidade": self.br_money_to_float(m.group(3)),
                        "tarifa_unitaria": self.br_money_to_float(m.group(4)),
                        "valor": val
                    })
        return itens

    def extract_scee(self, text):
        """Saldos e Créditos de Energia (O Saldo que ficou)"""
        bloco = self.safe_search(r"Demonstrativo de saldos SCEE.*?(?=A qualquer tempo|Periodos Band|$)", text, group=0)
        if not bloco: return {"participa": False}

        s_acum = self.safe_search(r"Saldo\s+Acumulado.*?\s+(\d+)", bloco)
        s_mes = self.safe_search(r"Saldo\s+M[eê]s.*?\s+(\d+)", bloco)
        s_exp = self.safe_search(r"Saldo\s+a\s+Expirar.*?\s+(\d+)", bloco)

        return {
            "participa": True,
            "saldos": {
                "mes": {"tp": int(s_mes) if s_mes else 0},
                "acumulado": {"tp": int(s_acum) if s_acum else 0},
                "a_expirar_proximo_mes": {"tp": int(s_exp) if s_exp else 0}
            },
            "observacoes": [self.normalize(bloco)]
        }

    def extract_historicos(self, text):
        """Histórico de Consumo (13 meses)"""
        bloco = self.safe_search(r"HISTÓRICO\s+DE\s+CONSUMO.*?kWh(.*?)(?:TOTAL|MEDIDOR|Reservado)", text)
        if not bloco: return {"consumo": {"registros": []}}

        pattern = r"([A-Z]{3})(\d{2})\s+([\d\.]+)\s+(\d+)"
        matches = re.findall(pattern, bloco)
        registros = []
        for m in matches:
            registros.append({
                "mes": f"{m[0]}{m[1]}",
                "ano": 2000 + int(m[1]),
                "kwh": int(m[2].replace('.', '')),
                "dias": int(m[3])
            })
        return {"consumo": {"unidade": "kWh", "registros": registros}}

    def extract_tributos(self, text):
        """Extração de ICMS, PIS e COFINS"""
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
        """Identifica períodos de bandeiras tarifárias"""
        bandeiras = []
        pattern = r"(Vermelha|Amarela|Verde)\s*P?\d?:\s*(\d{2}/\d{2})-(\d{2}/\d{2})"
        matches = re.findall(pattern, text)
        for m in matches:
            bandeiras.append({"tipo": m[0].upper(), "inicio": m[1], "fim": m[2]})
        return bandeiras