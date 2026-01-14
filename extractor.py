import re


class CopelExtractor:
    def __init__(self):
        # Números técnicos fixos que NÃO são a UC
        self.blacklist = [
            "9023307399", "04368898000106", "81200-240",
            "08005100116", "08006460012", "08004004343",
            "4635341388", "4434378300", "4432524551"
        ]

    def normalize(self, text):
        if not text: return ""
        text = re.sub(r"(Segunda Via|S e g u n d a V i a)", "", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def br_money_to_float(self, v):
        if not v: return 0.0
        v = str(v).replace("R$", "").replace(" ", "")
        sinal = -1 if "-" in v else 1
        v = v.replace("-", "").replace(".", "").replace(",", ".")
        try:
            return float(v) * sinal
        except:
            return 0.0

    def safe_search(self, pattern, text, group=1):
        if not text: return None
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return self.normalize(m.group(group)) if m else None

    def extract_all(self, text):
        fatura = self.extract_fatura_dados(text)
        cliente = self.extract_cliente_info(text)

        # Limpa UC de dentro do endereço
        if cliente['uc'] and cliente['endereco']['logradouro']:
            cliente['endereco']['logradouro'] = cliente['endereco']['logradouro'].replace(cliente['uc'], "").strip()

        return {
            "cliente": cliente,
            "fatura": fatura,
            "itens": self.extract_itens_detalhado(text),
            "medicoes": self.extract_medicoes(text),
            "historico": self.extract_historico(text),
            "tributos_consolidado": self.extract_tributos_resumo(text),
            "solar_scee": self.extract_saldos_gd(text),
            "gestao_debitos_e_bandeiras": self.extract_avis_e_debitos(text, fatura.get("mes_referencia"),
                                                                      fatura.get("vencimento")),
            "tecnico": self.extract_dados_tecnicos(text)
        }

    def extract_cliente_info(self, text):
        header = text[:2500]
        # UC - Prioridade absoluta para o número acima de "CÓDIGO DÉBITO AUTOMÁTICO"
        uc = self.safe_search(r"(\d{7,10})\s*CÓDIGO DÉBITO AUTOMÁTICO", header)

        if not uc:
            # Filtra códigos de município/IP para não pegar UC errada
            match_mun = re.search(r"Municipio\s+(\d+)", header)
            cod_mun = match_mun.group(1) if match_mun else "999999999"
            nums = re.findall(r"(?:\s|^)(\d{7,10})(?:\s|$)", header)
            uc = next((n for n in nums if n not in self.blacklist and n != cod_mun), None)

        ceps = re.findall(r"(\d{5}-\d{3})", header)
        cep_cliente = next((c for c in ceps if c != "81200-240"), None)

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*\n", header),
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", header),
            "endereco": {
                "logradouro": self.safe_search(r"Endereço:\s*(.*?)\s*CEP", header),
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-z\s\.\-]+)\s*-\s*Estado", header),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", header),
                "cep": cep_cliente
            }
        }

    def extract_fatura_dados(self, text):
        fin = re.search(r"(\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+R\$\s*([\d\.,\s-]+)", text)

        # PRÓXIMA LEITURA - Lógica baseada no quadro superior
        area_datas = text[:2000].replace("DATA DE EMISSÃO", "NF_EMISSAO")
        datas_seq = re.findall(r"(\d{2}/\d{2}/\d{4})", area_datas)
        prox_lei = datas_seq[-1] if len(datas_seq) >= 3 else None

        return {
            "mes_referencia": fin.group(1) if fin else None,
            "vencimento": fin.group(2) if fin else None,
            "valor_total": self.br_money_to_float(fin.group(3)) if fin else 0.0,
            "data_emissao": self.safe_search(r"DATA DE EMISSÃO:\s*(\d{2}/\d{2}/\d{4})", text),
            "proxima_leitura": prox_lei,
            "numero_fatura": self.safe_search(r"Nùmero da fatura:\s*([\w-]+)", text),
            "hash_fisco": self.safe_search(
                r"([A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4})",
                text)
        }

    def extract_historico(self, text):
        historico = []
        match = re.search(r"HISTÓRICO DE CONSUMO.*?Nº DIAS FAT\.(.*?)(?:Medidor|Reservado|TOTAL|$)", text, re.DOTALL)
        if match:
            rows = re.findall(r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)", match.group(1))
            for m, c, d in rows:
                historico.append({"mes": m, "consumo_kwh": int(c.replace('.', '')), "dias": int(d)})
        return historico

    def extract_itens_detalhado(self, text):
        itens = []
        pattern = r"^(.*?)\s+(kWh|UN|kW|un)\s+([\d\.,-]+)\s+([\d\.,-]+)\s+([\d\.,-]+)\s+([\d\.,-]+)\s+([\d\.,-]+)\s+([\d\.,-]+)"
        for line in text.split('\n'):
            m = re.search(pattern, line.strip())
            if m:
                desc = m.group(1).upper()
                if any(x in desc for x in ["TOTAL", "VALOR"]): continue
                tipo = "OUTROS"
                if "USO SISTEMA" in desc or "TUSD" in desc:
                    tipo = "TUSD"
                elif "CONSUMO" in desc or "TE " in desc:
                    tipo = "TE"
                elif any(x in desc for x in ["INJETADA", "COMPENSADA", "MPT", "GD"]):
                    tipo = "INJETADA"
                elif "ILUMIN" in desc or "COSIP" in desc:
                    tipo = "IP"
                elif any(x in desc for x in ["MULTA", "JUROS", "MORA", "ATUALIZA"]):
                    tipo = "FINANCEIRO"
                itens.append({
                    "descricao": m.group(1).strip(), "tipo": tipo, "quantidade": self.br_money_to_float(m.group(3)),
                    "valor_total": self.br_money_to_float(m.group(5)), "icms_valor": self.br_money_to_float(m.group(7)),
                    "tarifa_liquida": self.br_money_to_float(m.group(8))
                })
        return itens

    def extract_tributos_resumo(self, text):
        resumo = {}
        for t in ["ICMS", "PIS", "COFINS"]:
            pattern = rf"{t}\s+([\d\.,]+)\s+([\d\.,]+)%?\s+([\d\.,]+)"
            m = re.search(pattern, text)
            if m:
                resumo[t.lower()] = {
                    "base": self.br_money_to_float(m.group(1)),
                    "aliquota": float(m.group(2).replace(",", ".")),
                    "valor": self.br_money_to_float(m.group(3))
                }
        return resumo

    def extract_saldos_gd(self, text):
        txt = self.normalize(text).upper()
        atu = self.safe_search(r"SALDO ACUMULADO NO \(TP\).*?([\d\.]+)", txt) or \
              self.safe_search(r"SALDO ACUMULADO.*?([\d\.]+)", txt)
        expira = self.safe_search(r"SALDO A EXPIRAR PRÓXIMO MÊS.*?([\d\.]+)", txt)

        return {
            "saldo_anterior": self.br_money_to_float(self.safe_search(r"SALDO ANTERIOR.*?([\d\.]+)", txt)),
            "saldo_mes": self.br_money_to_float(self.safe_search(r"SALDO MÊS NO \(TP\).*?([\d\.]+)", txt)),
            "saldo_atual_acumulado": self.br_money_to_float(atu),
            "saldo_a_expirar_kwh": self.br_money_to_float(expira)
        }

    def extract_medicoes(self, text):
        medicoes = []
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)"
        for m in re.findall(pattern, text):
            medicoes.append({
                "medidor": m[0], "tipo": "GERACAO" if "GER" in m[1].upper() else "CONSUMO",
                "leitura_anterior": int(m[3].replace('.', '')), "leitura_atual": int(m[4].replace('.', '')),
                "consumo_apurado": self.br_money_to_float(m[6])
            })
        return medicoes

    def extract_avis_e_debitos(self, text, mes_ref, vencimento):
        # Filtro de meses para ignorar fatura atual no quadro de débitos
        mes_venc = vencimento[3:10] if vencimento else "99/9999"

        bloco_deb = self.safe_search(r"DEBITOS:\s*(.*)", text)
        lista_debitos = []
        if bloco_deb:
            matches = re.findall(r"(\d{2}/\d{4})\s+R\$\s*([\d\.,]+)", bloco_deb)
            for m, v in matches:
                if m != mes_ref and m != mes_venc:
                    lista_debitos.append({"mes": m, "valor": self.br_money_to_float(v)})

        area_band = self.safe_search(r"Periodos Band\.Tarif\.:\s*(.*?)(?:\n|TOTAL|$)", text)
        band_list = []
        if area_band:
            matches_band = re.findall(r"([A-Za-z \d]+):([\d/ \-]+)", area_band)
            for cor, periodo in matches_band:
                band_list.append({"cor": cor.strip(), "periodo": periodo.strip()})

        return {
            "contas_atrasadas": lista_debitos,
            "reaviso_corte": "REAVISO DE VENCIMENTO" in text.upper(),
            "detalhamento_bandeiras": band_list
        }

    def extract_dados_tecnicos(self, text):
        header = text[:2000]
        # Captura o responsável pela iluminação pública
        resp_ip = self.safe_search(r"Responsável pela Iluminação Pública:\s*(.*?)(?:\n|$)", header)

        return {
            "classificacao": self.safe_search(r"([A-Z]\d\s+.*?)\s+(?:Monofasico|Bifasico|Trifasico|/)", header),
            "tipo_fase": self.safe_search(r"(Monofasico|Bifasico|Trifasico)", header),
            "kwh_disponibilidade": 100 if "Trifasico" in header else (50 if "Bifasico" in header else 30),
            "modalidade_tarifaria": self.safe_search(r"Modalidade Tarifaria:\s*(.*?)(?:\n|Grupo|Periodos|$)",
                                                     text) or "CONVENCIONAL",
            "tensao_nominal_v": self.safe_search(r"Tensão Nominal\s*\(V\):\s*([\d/]+)", text),
            "limites_tensao": self.safe_search(r"Limites de Variação de Tensão\s*\(V\):\s*([\d\sA-Z/a-z]+)", text),
            "responsavel_ip": resp_ip,
            "disjuntor": self.safe_search(r"/\s*(\d+A)", header)
        }