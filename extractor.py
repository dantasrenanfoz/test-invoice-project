import re


class CopelExtractor:
    def __init__(self):
        # Lista de números que o OCR costuma confundir com a UC
        self.blacklist = [
            "9023307399", "04368898000106", "81200-240",
            "08005100116", "08006460012", "08004004343",
            "4635341388", "4434378300", "4432524551",
            "08004004343", "0800646012"
        ]

    def normalize(self, text):
        if not text:
            return ""
        # Limpa marcas d'água sem corromper o texto
        text = re.sub(r"(Segunda Via|S e g u n d a V i a)", "", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def br_money_to_float(self, v):
        if not v:
            return 0.0
        v = str(v).replace("R$", "").replace(" ", "")
        # Suporte para sinal de menos (Solar/Créditos)
        sinal = -1 if "-" in v else 1
        v = v.replace("-", "").replace(".", "").replace(",", ".")
        try:
            return float(v) * sinal
        except:
            return 0.0

    def safe_search(self, pattern, text, group=1):
        if not text:
            return None
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return self.normalize(m.group(group)) if m else None

    def extract_all(self, text):
        fatura = self.extract_fatura_dados(text)
        cliente = self.extract_cliente_info(text)

        # CORREÇÃO #2 E ATENÇÃO A: Limpeza inteligente de UC no logradouro
        if cliente['endereco']['logradouro']:
            logradouro = cliente['endereco']['logradouro']

            # Estratégia 1: Remove UC específica se identificada (apenas quando isolada)
            if cliente['uc'] and len(cliente['uc']) >= 7:
                # Remove UC apenas se ela aparecer isolada (com espaços, hífens ou no final)
                # Isso evita remover números válidos do endereço (ex: "Rua 123")
                pattern = rf"[\s\-,]+{re.escape(cliente['uc'])}(?=[\s\-,]|$)"
                logradouro = re.sub(pattern, ' ', logradouro)

            # Estratégia 2: Remove números de 7-10 dígitos isolados (provável UC)
            # Mas apenas se estiverem no meio ou final, nunca parte do nome da rua
            logradouro = re.sub(r'\s+\d{7,10}(?=\s+)', ' ', logradouro)  # No meio
            logradouro = re.sub(r'\s+\d{7,10}$', '', logradouro)  # No final

            # Normaliza espaços múltiplos
            cliente['endereco']['logradouro'] = re.sub(r'\s+', ' ', logradouro).strip()

        return {
            "cliente": cliente,
            "fatura": fatura,
            "itens": self.extract_itens_detalhado(text),
            "medicoes": self.extract_medicoes(text),
            "historico": self.extract_historico(text),
            "tributos": self.extract_tributos_resumo(text),
            "solar_scee": self.extract_saldos_gd(text),
            "avisos_debitos": self.extract_avisos_e_debitos(text, fatura.get("mes_referencia"),
                                                            fatura.get("vencimento")),
            "tecnico": self.extract_dados_tecnicos(text),
            "bandeiras": self.extract_bandeiras(text)
        }

    def extract_cliente_info(self, text):
        # CORREÇÃO #1: Extração de UC melhorada
        # Estratégia 1: Box UNIDADE CONSUMIDORA com variações de encoding
        box_uc = self.safe_search(r"UNIDADE\s*CONSUMIDORA[\s\n]+([\d\s\n]{7,15})", text)
        if not box_uc:
            # Variação com "Ú" mal codificado
            box_uc = self.safe_search(r"UNIDADE\s*CONS[UÚ]MIDORA[\s\n]+([\d\s\n]{7,15})", text)

        uc = re.sub(r"\D", "", box_uc) if box_uc else None

        # Estratégia 2: Procura por números de 7-10 dígitos próximos a palavras-chave
        if not uc or uc in self.blacklist or len(uc) < 7:
            # Tenta pegar UC do box destacado no topo da fatura
            uc_match = re.search(r"(?:Nome:|CPF:).*?(\d{7,10})", text[:1500], re.DOTALL)
            if uc_match:
                tentativa_uc = uc_match.group(1)
                if tentativa_uc not in self.blacklist and len(tentativa_uc) >= 7:
                    uc = tentativa_uc

        # Estratégia 3: Débito automático
        if not uc or uc in self.blacklist or len(uc) < 7:
            uc = self.safe_search(r"(\d{7,10})\s*(?:CÓ|CO)DIGO\s*(?:DÉ|DE)BITO\s*AUTOM", text)

        # Estratégia 4: Busca no logradouro (como último recurso)
        if not uc or uc in self.blacklist or len(uc) < 7:
            endereco_match = re.search(r"Endereço:\s*.*?(\d{7,10})", text[:1500])
            if endereco_match:
                tentativa_uc = endereco_match.group(1)
                if tentativa_uc not in self.blacklist and len(tentativa_uc) >= 7:
                    uc = tentativa_uc

        header = text[:2500]
        ceps = re.findall(r"(\d{5}-\d{3})", header)
        cep_cliente = next((c for c in ceps if c != "81200-240"), None)

        return {
            "nome": self.safe_search(r"Nome:\s*(.*?)\s*(?:\n|Endereço|End)", header),
            "uc": uc,
            "cpf_cnpj": self.safe_search(r"(?:CNPJ|CPF):\s*([\d\.\-\/\*]+)", header),
            "endereco": {
                "logradouro": self.safe_search(r"Endereço:\s*(.*?)\s*(?:CEP|Cidade)", header),
                "cidade": self.safe_search(r"Cidade:\s*([A-Za-zÀ-ÿ\s\.\-]+)\s*-\s*Estado", header),
                "estado": self.safe_search(r"Estado:\s*([A-Z]{2})", header),
                "cep": cep_cliente
            }
        }

    def extract_fatura_dados(self, text):
        # Padrão principal: MES/ANO VENCIMENTO VALOR
        fin = re.search(r"(\d{2}/20\d{2})\s+(\d{2}/\d{2}/20\d{2})\s+R\$\s*([\d\.,\s-]+)", text)

        # CORREÇÃO #8: Próxima leitura - Pattern correto
        # A próxima leitura não tem label, aparece como 4ª data no padrão:
        # data1 data2 dias data3 (onde data3 é a próxima leitura)
        prox = None

        # Padrão 1: Quatro datas no header (leitura_ant, leitura_atual, dias, PROXIMA)
        prox_pattern = re.search(r'(\d{2}/\d{2}/20\d{2})\s+(\d{2}/\d{2}/20\d{2})\s+(\d+)\s+(\d{2}/\d{2}/20\d{2})',
                                 text[:2000])
        if prox_pattern:
            prox = prox_pattern.group(4)  # A 4ª data é a próxima leitura

        # Padrão 2: Texto explícito "Próxima Leitura" (em alguns casos raros)
        if not prox:
            prox_match = re.search(r"Pr[oó]xima\s*Leitura[\s:]*(\d{2}/\d{2}/20\d{2})", text, re.I)
            if prox_match:
                prox = prox_match.group(1)

        # Chave de acesso de 44 dígitos
        chave = re.sub(r"\s+", "", self.safe_search(r"Chave\s*de\s*Acesso\s*([\d\s]{44,55})", text) or "")

        return {
            "mes_referencia": fin.group(1) if fin else None,
            "vencimento": fin.group(2) if fin else None,
            "valor_total": self.br_money_to_float(fin.group(3)) if fin else 0.0,
            "data_emissao": self.safe_search(r"DATA\s*DE\s*EMISS[AÃ]O:\s*(\d{2}/\d{2}/20\d{2})", text),
            "proxima_leitura": prox,
            "chave_acesso": chave if len(chave) == 44 else None,
            "numero_fatura": self.safe_search(r"N[uù]mero\s*da\s*fatura:\s*([\w-]+)", text),
            "hash_fisco": self.safe_search(
                r"([A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4}\.[A-Z0-9]{4})",
                text)
        }

    def extract_itens_detalhado(self, text):
        itens = []

        # Palavras-chave expandidas para capturar mais tipos de cobrança
        keywords = [
            "ENERGIA", "CONT ILUMIN", "MULTA", "JUROS", "ADICIONAL",
            "PARCELAMENTO", "ACRESCIMO", "PIS", "COFINS", "DEMANDA",
            "REAT", "BAND"
        ]

        for line in text.split('\n'):
            line = line.strip()

            # Identifica se a linha começa com descrição em caixa alta
            desc_match = re.search(r"^([A-Z\d\.\s/]{5,})", line)
            if not desc_match:
                continue

            desc = desc_match.group(1).strip()

            # Verifica se contém palavra-chave
            if not any(k in desc.upper() for k in keywords):
                continue

            # CORREÇÃO #5: Pula totalizadores E avisos
            if any(k in desc.upper() for k in ["TOTAL", "SUBTOTAL", "BASE DE C", "INCLUSO"]):
                continue

            # ============================================================================
            # CORREÇÃO CRÍTICA A e B: Limpeza de padrões problemáticos ANTES de extrair números
            # ============================================================================

            # Guarda a linha original para a descrição
            line_original = line

            # Remove datas no formato MM/AAAA (ex: 08/2024, 07/2024)
            # Isso evita capturar "08" e "2024" como números
            line_clean = re.sub(r'\b\d{2}/\d{4}\b', '', line)

            # Remove períodos P1, P2, etc. (ex: "BAND VM P1" → "BAND VM")
            # Isso evita capturar o "1" ou "2" como quantidade
            line_clean = re.sub(r'\sP\d+\b', '', line_clean)

            # Remove formato de parcelas (ex: 004/012, 01/12)
            # Isso evita capturar números de parcelas
            line_clean = re.sub(r'\b\d{1,3}/\d{1,3}\b', '', line_clean)

            # ============================================================================
            # Extrai números APENAS da linha limpa
            # ============================================================================

            # Agora sim, extrai apenas números que são valores monetários ou quantidades
            # Prioriza números com vírgula (valores monetários)
            nums = re.findall(r"(-?[\d\.]*,\d+|-?\d+)", line_clean)

            if len(nums) < 2:
                continue

            try:
                # Determina tipo de item
                tipo = "OUTROS"
                if "USO SISTEMA" in desc or "TUSD" in desc:
                    tipo = "TUSD"
                elif "CONSUMO" in desc or " TE " in desc or "ELET CONSUMO" in desc:
                    tipo = "TE"
                elif any(x in desc for x in ["INJETADA", "COMPENSADA", "GD", "INJ"]):
                    tipo = "INJETADA"
                elif "ILUMIN" in desc or "COSIP" in desc or "IP" in desc:
                    tipo = "IP"
                elif any(x in desc for x in ["MULTA", "JUROS", "MORA", "PARCEL", "ACRES"]):
                    tipo = "FINANCEIRO"
                elif "BAND" in desc or "AMARELA" in desc or "VERMELHA" in desc or "TRIB DIF" in desc:
                    tipo = "BANDEIRA"
                elif "DEMANDA" in desc:
                    tipo = "DEMANDA"

                # CORREÇÃO #3: Extração correta de valores
                # Padrão típico da linha Copel:
                # ENERGIA ELET CONSUMO kWh 266 0,382519 101,75 5,23 19,33 0,290190
                #                          [0]    [1]     [2]   [3]  [4]    [5]

                quantidade = self.br_money_to_float(nums[0])

                # Para itens financeiros sem quantidade (multa, juros)
                if tipo == "FINANCEIRO" and "UN" in line_original and quantidade == 1:
                    tarifa = self.br_money_to_float(nums[1]) if len(nums) >= 2 else 0.0
                    valor_total = tarifa
                    icms = 0.0
                # Para itens de energia (TE, TUSD, BANDEIRA, INJETADA)
                elif tipo in ["TE", "TUSD", "BANDEIRA", "INJETADA"]:
                    # Padrão: qtd, tarifa, VALOR_TOTAL, icms, outros...
                    tarifa = self.br_money_to_float(nums[1]) if len(nums) >= 2 else 0.0
                    valor_total = self.br_money_to_float(nums[2]) if len(nums) >= 3 else 0.0
                    icms = self.br_money_to_float(nums[3]) if len(nums) >= 4 else 0.0
                # Para IP (iluminação pública)
                elif tipo == "IP":
                    # Padrão: UN 1 25,780000 25,78
                    if "UN" in line_original:
                        quantidade = 1
                        tarifa = self.br_money_to_float(nums[-1])
                        valor_total = tarifa
                        icms = 0.0
                    else:
                        tarifa = self.br_money_to_float(nums[1]) if len(nums) >= 2 else 0.0
                        valor_total = self.br_money_to_float(nums[2]) if len(nums) >= 3 else 0.0
                        icms = 0.0
                else:
                    # Fallback para outros tipos
                    tarifa = self.br_money_to_float(nums[1]) if len(nums) >= 2 else 0.0
                    valor_total = self.br_money_to_float(nums[-1])
                    icms = 0.0

                # Validação: descarta itens com valores absurdos (indicativo de parsing errado)
                # Tarifa não pode ser > 100 reais por kWh
                # Quantidade não pode ser > 100000 kWh (consumo residencial típico < 2000)
                if abs(tarifa) > 100 or abs(quantidade) > 100000:
                    continue

                itens.append({
                    "descricao": desc,
                    "tipo": tipo,
                    "quantidade": round(quantidade, 2),
                    "tarifa_unitaria": round(tarifa, 6),
                    "valor_total": round(valor_total, 2),
                    "icms": round(icms, 2)
                })
            except:
                continue

        return itens

    def extract_medicoes(self, text):
        medicoes = []

        # Padrão para medições
        pattern = r"(\d{8,})\s+(CONSUMO|GERAC)\s+kWh\s*([A-Z]{2}|)\s+([\d\.]+)\s+([\d\.]+)\s+(\d+)\s+([\d\.]+)"

        for m in re.findall(pattern, text):
            leit_ant = int(m[3].replace('.', ''))
            leit_atual = int(m[4].replace('.', ''))

            medicoes.append({
                "numero_medidor": m[0],
                "tipo": "GERACAO" if "GER" in m[1].upper() else "CONSUMO",
                "constante": int(m[5]) if m[5] else 1,
                "leitura_anterior": leit_ant,
                "leitura_atual": leit_atual,
                "consumo_kwh": leit_atual - leit_ant if leit_atual >= leit_ant else 0
            })

        return medicoes

    def extract_historico(self, text):
        hist = []

        # Busca o bloco de histórico
        match = re.search(
            r"HISTÓRICO DE CONSUMO.*?CONSUMO FATURADO\s+Nº DIAS FAT\.(.*?)(?:Medidor|Reservado|TOTAL|Periodo|$)", text,
            re.DOTALL)

        if match:
            # Extrai linhas: MES24 consumo dias
            rows = re.findall(r"([A-Z]{3}\d{2})\s+([\d\.]+)\s+(\d+)", match.group(1))
            for mes, kwh, dias in rows:
                hist.append({
                    "mes_ano": mes,
                    "consumo_kwh": int(kwh.replace('.', '')),
                    "dias_faturados": int(dias)
                })

        return hist

    def extract_tributos_resumo(self, text):
        tributos = {}

        # CORREÇÃO #6: Extração de tributos com múltiplos padrões

        # === ICMS - sempre em tabela ===
        for pattern in [
            r"ICMS\s+([\d\.,]+)\s+([\d\.,]+)%?\s+([\d\.,]+)",
            r"ICMS[:\s]+([\d\.,]+)[^\d]+([\d\.,]+)%[^\d]+([\d\.,]+)"
        ]:
            m = re.search(pattern, text)
            if m:
                tributos['icms'] = {
                    "base_calculo": self.br_money_to_float(m.group(1)),
                    "aliquota_percentual": float(m.group(2).replace(",", ".")),
                    "valor": self.br_money_to_float(m.group(3))
                }
                break

        # === PIS e COFINS - podem estar em tabela OU no texto "INCLUSO" ===

        # Primeiro tenta extrair do texto "INCLUSO NA FATURA"
        incluso_match = re.search(r"INCLUSO NA FATURA PIS R\$([\d\.,]+) E COFINS R\$([\d\.,]+)", text, re.I)

        if incluso_match:
            # Encontrou no texto INCLUSO - extrai valores diretos
            pis_valor = self.br_money_to_float(incluso_match.group(1))
            cofins_valor = self.br_money_to_float(incluso_match.group(2))

            # Para PIS e COFINS do texto INCLUSO, não temos base de cálculo
            # Vamos usar o valor e alíquotas típicas da Copel
            tributos['pis'] = {
                "base_calculo": 0.0,  # Não disponível neste formato
                "aliquota_percentual": 1.11,  # Alíquota típica PIS
                "valor": pis_valor
            }

            tributos['cofins'] = {
                "base_calculo": 0.0,  # Não disponível neste formato
                "aliquota_percentual": 5.13,  # Alíquota típica COFINS
                "valor": cofins_valor
            }

        else:
            # Não encontrou no INCLUSO, tenta tabela
            for tributo_nome, tributo_key in [("PIS", "pis"), ("COFINS", "cofins")]:
                for pattern in [
                    rf"{tributo_nome}\s+([\d\.,]+)\s+([\d\.,]+)%?\s+([\d\.,]+)",
                    rf"{tributo_nome}[:\s]+([\d\.,]+)[^\d]+([\d\.,]+)%[^\d]+([\d\.,]+)"
                ]:
                    m = re.search(pattern, text)
                    if m:
                        tributos[tributo_key] = {
                            "base_calculo": self.br_money_to_float(m.group(1)),
                            "aliquota_percentual": float(m.group(2).replace(",", ".")),
                            "valor": self.br_money_to_float(m.group(3))
                        }
                        break

        return tributos

    def extract_saldos_gd(self, text):
        """Extrai saldos de geração distribuída (SCEE)"""
        txt = self.normalize(text).upper()

        # Verifica se é UC geradora ou beneficiária
        is_geradora = "MICRO/MINIGERADORA NO SCEE" in txt
        is_beneficiaria = "BENEFICIARIA SCEE" in txt or "UC BENEFICIARIA" in txt

        if not (is_geradora or is_beneficiaria):
            return None

        # Extrai UC geradora se for beneficiária
        uc_geradora = None
        if is_beneficiaria:
            uc_match = re.search(r"GERADORA:\s*UC\s*(\d+)", txt)
            if uc_match:
                uc_geradora = uc_match.group(1)

        # Extrai saldos
        saldo_mes = self.safe_search(r"SALDO M[EÊ]S.*?([\d\.]+)", txt)
        saldo_acum = self.safe_search(r"SALDO ACUMULADO.*?([\d\.]+)", txt)
        saldo_expirar = self.safe_search(r"SALDO A EXPIRAR.*?([\d\.]+)", txt)

        # Para faturas mais recentes com discriminação por período
        saldo_mes_ponta = self.safe_search(r"SALDO M[EÊ]S PONTA\s*([\d\.]+)", txt)
        saldo_mes_fponta = self.safe_search(r"SALDO M[EÊ]S F PONTA\s*([\d\.]+)", txt)
        saldo_acum_ponta = self.safe_search(r"SALDO ACUMULADO PONTA\s*([\d\.]+)", txt)
        saldo_acum_fponta = self.safe_search(r"SALDO ACUMULADO F PONTA\s*([\d\.]+)", txt)

        result = {
            "tipo": "GERADORA" if is_geradora else "BENEFICIARIA",
            "uc_geradora": uc_geradora,
            "saldo_mes_kwh": self.br_money_to_float(saldo_mes) if saldo_mes else 0.0,
            "saldo_acumulado_kwh": self.br_money_to_float(saldo_acum) if saldo_acum else 0.0,
            "saldo_expirar_kwh": self.br_money_to_float(saldo_expirar) if saldo_expirar else 0.0
        }

        # Adiciona discriminação por período se disponível
        if saldo_mes_ponta or saldo_mes_fponta:
            result["detalhamento_periodos"] = {
                "saldo_mes_ponta": self.br_money_to_float(saldo_mes_ponta) if saldo_mes_ponta else 0.0,
                "saldo_mes_fora_ponta": self.br_money_to_float(saldo_mes_fponta) if saldo_mes_fponta else 0.0,
                "saldo_acum_ponta": self.br_money_to_float(saldo_acum_ponta) if saldo_acum_ponta else 0.0,
                "saldo_acum_fora_ponta": self.br_money_to_float(saldo_acum_fponta) if saldo_acum_fponta else 0.0
            }

        return result

    def extract_avisos_e_debitos(self, text, mes_ref, vencimento):
        """Extrai débitos anteriores e avisos"""
        bloco_deb = self.safe_search(r"(?:DEBITOS|D[ÉE]BITOS):\s*(.*?)(?:\n\n|Caso|$)", text, 1)

        debitos_lista = []
        if bloco_deb:
            matches = re.findall(r"(\d{2}/\d{4})\s+R\$\s*([\d\.,]+)", bloco_deb)
            for m, v in matches:
                if m != mes_ref:
                    debitos_lista.append({
                        "mes_ano": m,
                        "valor": self.br_money_to_float(v)
                    })

        return {
            "debitos_anteriores": debitos_lista,
            "total_debitos": sum(d["valor"] for d in debitos_lista),
            "quantidade_faturas_atrasadas": len(debitos_lista),
            "aviso_corte": "REAVISO" in text.upper() or "SUJEITA AO CORTE" in text.upper(),
            "fatura_paga": "CONTA PAGA" in text.upper() or "ARRECADADA" in text.upper()
        }

    def extract_bandeiras(self, text):
        """Extrai informações sobre bandeiras tarifárias"""
        txt = text.upper()

        # Procura pelo aviso de períodos de bandeiras
        band_match = re.search(r"PER[IÍ]ODOS BAND\.TARIF\.:\s*(.*?)(?:\n|$)", txt)

        if not band_match:
            return None

        band_text = band_match.group(1)

        bandeiras = []

        # Extrai cada período
        # Formato: "Verde:15/05-13/06" ou "Amarela:09/07-31/07"
        periodos = re.findall(r"(VERDE|AMARELA|VERMELHA)\s*P?(\d*):\s*(\d{2}/\d{2})-(\d{2}/\d{2})", band_text)

        for cor, periodo_tipo, inicio, fim in periodos:
            bandeiras.append({
                "tipo": cor.capitalize(),
                "periodo": periodo_tipo if periodo_tipo else None,
                "data_inicio": inicio,
                "data_fim": fim
            })

        return bandeiras if bandeiras else None

    def extract_dados_tecnicos(self, text):
        header = text[:3000]

        # CORREÇÃO #7: Classificação e tipo de fornecimento com encoding variável
        # Tenta diferentes variações de acentuação
        classif = self.safe_search(r"Classifica[çc][aã]o:\s*(.*?)\s*(?:Tipo|DATAS|\n)", header)
        if not classif:
            # Tenta sem acento
            classif = self.safe_search(r"Classificacao:\s*(.*?)\s*(?:Tipo|DATAS|\n)", header)

        tipo_forn = self.safe_search(r"Tipo\s*de\s*Fornecimento:\s*(.*?)(?:\n|DATAS|Leitura)", header)

        # Extrai fase
        fase = None
        if "TRIFASICO" in header.upper() or "TRIFÃSICO" in header.upper():
            fase = "Trifasico"
        elif "BIFASICO" in header.upper() or "BIFÃSICO" in header.upper():
            fase = "Bifasico"
        elif "MONOFASICO" in header.upper() or "MONOFÃSICO" in header.upper():
            fase = "Monofasico"

        # Se não encontrou nos boxes, tenta no cabeçalho geral
        if not classif:
            classif_match = re.search(r"(B\d+\s+[A-Za-z]+\s*/\s*[A-Za-z\s]+)", header[:500])
            if classif_match:
                classif = classif_match.group(1).strip()

        # Disponibilidade por tipo de fase
        disp_kwh = 100 if fase == "Trifasico" else (50 if fase == "Bifasico" else 30)

        # Tensão
        tensao = self.safe_search(r"Tensão\s*Nominal.*?([\d/]+)\s*V", text)

        # CORREÇÃO #4: Responsável IP - limita captura
        resp_ip = None
        # Pattern que para na primeira quebra de linha ou número grande
        resp_match = re.search(r"Responsável pela Iluminação Pública:\s*([^\n\r]{1,100})", header)
        if resp_match:
            resp_ip = resp_match.group(1).strip()
            # Remove tudo após números de telefone ou data
            resp_ip = re.split(r'\d{10,}|\d{2}/\d{2}/\d{4}|B\d+\s+Residencial', resp_ip)[0].strip()
            # Remove números de telefone curtos
            resp_ip = re.sub(r'\s+\d{8,}', '', resp_ip).strip()

        # Modalidade tarifária
        modalidade = self.safe_search(r"Modalidade\s*Tarif[aá]ria:\s*(.*?)(?:\n|Grupo|$)", text)

        # Disjuntor
        disj = self.safe_search(r"/\s*(\d+A)", header)

        # Grupo tarifário
        grupo = self.safe_search(r"Grupo de Tens[aã]o.*?([AB])\s*-", text)

        # Tarifa social
        is_social = "TARIFA SOCIAL" in header.upper() or "BAIXA RENDA" in header.upper()

        return {
            "classificacao": classif,
            "tipo_fornecimento": tipo_forn,
            "tipo_fase": fase,
            "disponibilidade_kwh": disp_kwh,
            "tensao_nominal": tensao,
            "disjuntor": disj,
            "modalidade_tarifaria": modalidade or "CONVENCIONAL",
            "grupo_tarifario": grupo,
            "tarifa_social": is_social,
            "responsavel_iluminacao": resp_ip
        }