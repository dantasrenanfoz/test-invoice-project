# Usa uma versão leve do Python
FROM python:3.10-slim

# 1. Instala o Tesseract e as dependências do OpenCV no Linux do Render
# O 'no-install-recommends' ajuda a economizar espaço para caber no plano Free
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-por \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Define a pasta de trabalho
WORKDIR /app

# 3. Copia e instala as bibliotecas Python
COPY requirements.txt .
# O --no-cache-dir ajuda a não estourar o limite de disco do build
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copia o restante do seu código
COPY . .

# 5. Comando para iniciar a API (ajuste o nome do arquivo se for diferente)
# IMPORTANTE: No Render, a porta deve ser a variável de ambiente $PORT ou 80
CMD ["uvicorn", "ocr_api:app", "--host", "0.0.0.0", "--port", "10000"]