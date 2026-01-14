from fastapi import FastAPI, UploadFile, File, HTTPException
import pdfplumber
import io
import uvicorn
from extractor import CopelExtractor

app = FastAPI(title="Lex Energia Extractor API")
ex = CopelExtractor()


@app.post("/processar-fatura")
async def processar_fatura(pdf: UploadFile = File(...)):
    # Validação simples de arquivo
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="O arquivo enviado deve ser um PDF.")

    try:
        content = await pdf.read()

        with pdfplumber.open(io.BytesIO(content)) as p:
            # Extrai texto de todas as páginas
            raw_text = "\n".join([page.extract_text() or "" for page in p.pages])

        if not raw_text.strip():
            raise HTTPException(status_code=422, detail="Não foi possível extrair texto do PDF (pode ser uma imagem).")

        # Extração completa usando a classe CopelExtractor
        dados = ex.extract_all(raw_text)

        # ============================================================================
        # CORREÇÃO CRÍTICA C: Cálculos de Energia Solar
        # ============================================================================

        itens = dados['itens']

        # INJETADA: Soma o valor ABSOLUTO (energia injetada é negativa)
        inj = sum(abs(i['quantidade']) for i in itens if i['tipo'] == "INJETADA")

        # CONSUMIDA: Usa APENAS TE (Tarifa de Energia)
        # ⚠️ IMPORTANTE: TE e TUSD incidem sobre o MESMO kWh consumido!
        # Somar os dois dobraria o consumo real.
        #
        # Exemplo:
        # - Cliente consumiu 300 kWh
        # - Paga TE:   R$ 0,40/kWh × 300 = R$ 120,00
        # - Paga TUSD: R$ 0,45/kWh × 300 = R$ 135,00
        # - Consumo real = 300 kWh (NÃO 600!)
        cons = sum(i['quantidade'] for i in itens if i['tipo'] == "TE" and i['quantidade'] > 0)

        # Cálculo de compensação solar (energia injetada que abate do consumo)
        # Na prática, a energia injetada compensa o consumo de energia
        consumo_liquido = max(cons - inj, 0)  # Consumo após compensação solar
        economia_solar = min(inj, cons)  # Energia efetivamente compensada

        # Percentual de abatimento (quanto da energia consumida foi compensada)
        percentual_abatimento = round((economia_solar / cons) * 100, 2) if cons > 0 else 0

        # Verifica se a UC é autossuficiente (injeta mais do que consome)
        autossuficiente = inj >= cons if cons > 0 else False

        # Cálculo de créditos (energia injetada que sobra para outros meses)
        creditos_gerados = max(inj - cons, 0) if cons > 0 else inj

        dados["analise_energia_solar"] = {
            # Valores básicos
            "total_consumido_kwh": round(cons, 2),
            "total_injetado_kwh": round(inj, 2),

            # Análise de compensação
            "consumo_liquido_kwh": round(consumo_liquido, 2),
            "economia_solar_kwh": round(economia_solar, 2),
            "percentual_abatimento": percentual_abatimento,

            # Status da UC
            "autossuficiente": autossuficiente,
            "creditos_gerados_kwh": round(creditos_gerados, 2),

            # Metadados
            "chave_acesso": dados['fatura'].get('chave_acesso'),
            "mes_referencia": dados['fatura'].get('mes_referencia'),

            # Detalhamento financeiro (se disponível)
            "valor_total_fatura": dados['fatura'].get('valor_total', 0),

            # Informação sobre método de cálculo
            "_observacao": "Consumo calculado usando apenas TE (Tarifa de Energia). TE e TUSD incidem sobre o mesmo kWh."
        }

        # ============================================================================
        # Análise adicional: Identificação de anomalias
        # ============================================================================

        anomalias = []

        # Verifica se há valores suspeitos nos itens
        for item in itens:
            # Tarifa muito alta (pode indicar parsing errado)
            if item['tipo'] in ['TE', 'TUSD'] and abs(item.get('tarifa_unitaria', 0)) > 10:
                anomalias.append({
                    "tipo": "tarifa_alta",
                    "descricao": f"Tarifa unitária suspeita: R$ {item['tarifa_unitaria']}/kWh",
                    "item": item['descricao']
                })

            # Quantidade muito alta para residencial
            if item['tipo'] in ['TE', 'TUSD'] and abs(item.get('quantidade', 0)) > 10000:
                anomalias.append({
                    "tipo": "quantidade_alta",
                    "descricao": f"Quantidade suspeita: {item['quantidade']} kWh",
                    "item": item['descricao']
                })

        # Verifica se há inconsistência entre consumo e injeção
        if cons > 0 and inj > cons * 3:
            anomalias.append({
                "tipo": "injecao_alta",
                "descricao": f"Injeção ({inj} kWh) é mais de 3x o consumo ({cons} kWh)",
                "item": "Análise geral"
            })

        if anomalias:
            dados["anomalias_detectadas"] = anomalias

        return dados

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")


@app.get("/health")
async def health_check():
    """Endpoint de health check para monitoramento"""
    return {
        "status": "healthy",
        "service": "Lex Energia Extractor API",
        "version": "3.0"
    }


@app.get("/")
async def root():
    """Endpoint raiz com informações da API"""
    return {
        "message": "Lex Energia Extractor API",
        "version": "3.0",
        "endpoints": {
            "processar_fatura": "POST /processar-fatura",
            "health": "GET /health",
            "docs": "GET /docs"
        },
        "changelog": {
            "3.0": [
                "Correção crítica: Consumo agora usa apenas TE (não soma TE+TUSD)",
                "Adicionado cálculo de consumo líquido e economia solar",
                "Adicionado detector de anomalias",
                "Adicionado indicador de autossuficiência",
                "Adicionado cálculo de créditos gerados"
            ]
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)