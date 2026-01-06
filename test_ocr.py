import pytesseract
from PIL import Image

img = Image.open("faturacopel.jpg")
print(pytesseract.image_to_string(img, lang="por"))
