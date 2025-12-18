import requests

# URL da sua API de OCR
url = "http://127.0.0.1:8001/ler-fatura-foto"

# Caminho da imagem que você baixou
arquivo_imagem = "faturacopel.jpg"

try:
    with open(arquivo_imagem, "rb") as f:
        files = {"file": (arquivo_imagem, f, "image/jpeg")}
        print(f"Enviando {arquivo_imagem} para processamento...")

        response = requests.post(url, files=files)

        if response.status_code == 200:
            print("\n--- SUCESSO! JSON RETORNADO: ---\n")
            import json

            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Erro: {response.status_code}")
            print(response.text)

except FileNotFoundError:
    print(f"Erro: Coloque o arquivo '{arquivo_imagem}' na mesma pasta desse script.")