import io
import os
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

APP_ID = os.getenv("ONTRAPORT_APP_ID")
API_KEY = os.getenv("ONTRAPORT_API_KEY")

HEADERS = {
    "Api-Appid": APP_ID,
    "Api-Key": API_KEY,
}

# 1. URL de la foto que mencionas
WEBP_URL = "https://i.ontraport.com/183266.4f95ec89aef6b69811b9ad6d8eafd5e6.WEBP"

print("1. Descargando y convirtiendo imagen...")
response = requests.get(WEBP_URL)
response.raise_for_status()

# Convertir WebP a JPEG en memoria
image = Image.open(io.BytesIO(response.content))
if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
    image = image.convert("RGB")

jpeg_buffer = io.BytesIO()
image.save(jpeg_buffer, format="JPEG", quality=95)
jpeg_buffer.seek(0)
print("-> Conversión completada con éxito.")

# 2. Probar subida vía API
print("2. Intentando subir JPEG a Ontraport...")
files = {
    "file": ("profile.jpg", jpeg_buffer, "image/jpeg")
}

# Probamos el endpoint estándar de carga de archivos de Ontraport API
upload_url = "https://api.ontraport.com/1/file/upload"
upload_res = requests.post(upload_url, headers=HEADERS, files=files)

print("Status Code:", upload_res.status_code)
print("Respuesta:", upload_res.text)