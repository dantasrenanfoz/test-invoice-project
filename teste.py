import os
import json
import pdfplumber
from extractor import CopelExtractor

# ConfiguraÃ§Ãµes
PASTA_PDFS = r"D:\filtrado"
ARQUIVO_SAIDA = "resultado_todos_pdfs.txt"

# Inicializa o extrator profissional
ex = CopelExtractor()


def processar_pdf(caminho_pdf):
    nome_arquivo = os.path.basename(caminho_pdf)

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            # Extrai texto de todas as pÃ¡ginas e une em uma string
            raw_text = "\n".join([page.extract_text() or "" for page in pdf.pages])

        # MÃ‰TODO AUTOMÃTICO: extract_all traz todos os mÃ³dulos (histÃ³rico, tributos, solar, etc)
        # Se novos campos forem adicionados no extrator, eles aparecerÃ£o aqui automaticamente.
        dados_extraidos = ex.extract_all(raw_text)

        # Adiciona metadados do arquivo
        resultado = {
            "arquivo": nome_arquivo,
            "status": "OK",
            "dados": dados_extraidos
        }

        print(f"âœ” Sucesso: {nome_arquivo}")
        return resultado

    except Exception as e:
        print(f"âŒ Erro em {nome_arquivo}: {str(e)}")
        return {
            "arquivo": nome_arquivo,
            "status": "ERRO",
            "erro": str(e)
        }


def main():
    if not os.path.exists(PASTA_PDFS):
        print(f"Erro: A pasta {PASTA_PDFS} nÃ£o existe.")
        return

    resultados = []

    # Lista arquivos e processa
    arquivos = [f for f in os.listdir(PASTA_PDFS) if f.lower().endswith(".pdf")]

    if not arquivos:
        print("Nenhum PDF encontrado na pasta.")
        return

    for arquivo in arquivos:
        caminho = os.path.join(PASTA_PDFS, arquivo)
        res = processar_pdf(caminho)
        resultados.append(res)

    # GravaÃ§Ã£o do arquivo de saÃ­da
    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        for r in resultados:
            f.write("=================================================\n")
            f.write(f"ARQUIVO: {r['arquivo']}\n")
            f.write(f"STATUS : {r['status']}\n\n")
            # ensure_ascii=False permite acentos e R$ no arquivo de texto
            f.write(json.dumps(r.get("dados", r), ensure_ascii=False, indent=2))
            f.write("\n\n")

    print(f"\nâœ… Processamento concluÃ­do! Verifique o arquivo: {ARQUIVO_SAIDA}")


if __name__ == "__main__":
    main()