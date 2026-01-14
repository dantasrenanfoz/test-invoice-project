import os
import pdfplumber
from extractor import CopelExtractor

PASTA_PDFS = r"D:\filtrado"
PASTA_LOG = "logs_testes"

os.makedirs(PASTA_LOG, exist_ok=True)

ex = CopelExtractor()

def processar_pdf(caminho_pdf):
    nome = os.path.basename(caminho_pdf)
    log_path = os.path.join(PASTA_LOG, nome.replace(".pdf", ".txt"))

    try:
        with pdfplumber.open(caminho_pdf) as p:
            texto = "\n".join([page.extract_text() or "" for page in p.pages])

        cliente = ex.extract_cliente_info(texto)
        fatura = ex.extract_fatura_dados(texto)
        itens = ex.extract_itens_faturados(texto)
        medicoes = ex.extract_medicoes(texto)
        obs = ex.extract_observacoes(texto)

        with open(log_path, "w", encoding="utf-8") as f:
            f.write("=== CLIENTE ===\n")
            f.write(str(cliente) + "\n\n")

            f.write("=== FATURA ===\n")
            f.write(str(fatura) + "\n\n")

            f.write("=== ITENS ===\n")
            for i in itens:
                f.write(str(i) + "\n")

            f.write("\n=== MEDIÇÕES ===\n")
            for m in medicoes:
                f.write(str(m) + "\n")

            f.write("\n=== OBSERVAÇÕES ===\n")
            f.write(str(obs) + "\n")

        print(f"✔ OK: {nome}")

    except Exception as e:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("❌ ERRO AO PROCESSAR PDF\n")
            f.write(str(e))

        print(f"❌ ERRO: {nome} -> {e}")

def main():
    for arquivo in os.listdir(PASTA_PDFS):
        if arquivo.lower().endswith(".pdf"):
            caminho = os.path.join(PASTA_PDFS, arquivo)
            processar_pdf(caminho)

if __name__ == "__main__":
    main()
