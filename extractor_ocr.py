import cv2
import pytesseract
from PIL import Image
import os
import numpy as np
import pdfplumber
from pathlib import Path

# ==============================================================================
# IMPORTAÇÃO DA LÓGICA EXISTENTE (Não mexemos no extrator de PDF)
# ==============================================================================
from extractor import process_copel_bill

# ==============================================================================
# CONFIGURAÇÃO TESSERACT
# ==============================================================================
# Ajuste o caminho se necessário
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def prepare_image_for_ocr(image_path):
    """
    Prepara a foto para leitura:
    1. Aumenta a resolução (Zoom).
    2. Remove o fundo laranja usando o Canal Vermelho (Truque de contraste).
    3. Aplica limpeza de ruído.
    """
    try:
        # 1. Carrega a imagem
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Imagem não encontrada: {image_path}")

        # 2. Aumenta a imagem (Upscaling 3x)
        # Isso ajuda muito a ler letras pequenas e pontilhados
        img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        # 3. TRUQUE DO CANAL VERMELHO (Específico para Faturas Laranjas)
        # Em vez de converter para cinza direto, pegamos só a "camada vermelha" da foto.
        # Como o fundo é laranja (tem muito vermelho), ele vira BRANCO.
        # O texto preto (tem pouco vermelho) continua PRETO.
        # Isso "apaga" o fundo colorido.
        b, g, r = cv2.split(img)

        # 4. Aumenta contraste (CLAHE) na camada vermelha
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl1 = clahe.apply(r)

        # 5. Binarização (Preto e Branco Puro)
        # Threshold OTSU para definir o que é letra e o que é papel
        ret, thresh = cv2.threshold(cl1, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 6. Limpeza final (Remove pontinhos de sujeira da câmera)
        kernel = np.ones((2, 2), np.uint8)
        clean = cv2.erode(thresh, kernel, iterations=1)

        # Opcional: Salvar imagem processada para você ver
        # cv2.imwrite("debug_imagem_limpa.jpg", clean)

        return Image.fromarray(clean)

    except Exception as e:
        print(f"Erro no tratamento da imagem: {e}")
        return None


def process_image_bill(image_path):
    temp_pdf_path = str(image_path) + ".temp.pdf"

    try:
        print(f"🔄 Processando foto da câmera: {image_path}")

        # 1. Tratamento da Imagem
        pil_image = prepare_image_for_ocr(image_path)
        if not pil_image:
            return {"status": "erro", "mensagem": "Falha ao tratar a imagem."}

        # 2. OCR -> PDF Invisível
        # --psm 4: Assume texto de tamanho variável (bom para faturas)
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(
            pil_image,
            extension='pdf',
            lang='por',
            config='--psm 4'
        )

        # 3. Salva PDF temporário
        with open(temp_pdf_path, "wb") as f:
            f.write(pdf_bytes)

        # 4. DEBUG (Verifica se leu algo)
        try:
            with pdfplumber.open(temp_pdf_path) as debug_pdf:
                texto = debug_pdf.pages[0].extract_text() or ""
                print("\n" + "=" * 30)
                print("O ROBÔ LEU ISSO NA FOTO:")
                print(texto[:500] + "...")  # Mostra o começo do texto
                print("=" * 30 + "\n")
        except:
            pass

        # 5. Chama o extrator oficial (O mesmo do PDF de email)
        # Ele vai ler o PDF temporário que criamos a partir da foto
        resultado = process_copel_bill(temp_pdf_path)

        # Marca a origem
        if isinstance(resultado, dict):
            resultado["origem_processamento"] = "Câmera (OCR)"
            # Se falhou em ler dados vitais, avisa
            dados = resultado.get("dados_extraidos", {}).get("referencia_fatura", {})
            if not dados.get("total_pagar") and not dados.get("vencimento"):
                resultado["aviso_qualidade"] = "A foto pode estar tremida ou com sombra. Tente novamente."

        return resultado

    except Exception as e:
        return {"status": "erro", "mensagem": f"Erro OCR: {str(e)}"}

    finally:
        if os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except:
                pass


if __name__ == "__main__":
    # Teste rápido local
    imagem = "faturacopel.jpg"
    if os.path.exists(imagem):
        import json

        print(json.dumps(process_image_bill(imagem), indent=2, ensure_ascii=False))