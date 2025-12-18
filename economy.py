def calcular_economia(valor_fatura, percentual=0.10):
    economia_mensal = round(valor_fatura * percentual, 2)
    economia_anual = round(economia_mensal * 12, 2)
    valor_com_desconto = round(valor_fatura - economia_mensal, 2)

    return {
        "percentual_desconto": int(percentual * 100),
        "economia_mensal": economia_mensal,
        "economia_anual": economia_anual,
        "valor_com_desconto": valor_com_desconto
    }
