import io
import os
import re
import sys
import time
import jwt
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# --- Configuración Ontraport ---
APP_ID = os.getenv("ONTRAPORT_APP_ID")
API_KEY = os.getenv("ONTRAPORT_API_KEY")
AID = os.getenv("ONTRAPORT_AID", "183266")
CSRF = os.getenv("ONTRAPORT_CSRF")
COOKIE = os.getenv("ONTRAPORT_COOKIE")

FIELD_IMAGE = "f3151"
API_BASE_URL = "https://api.ontraport.com/1"

API_HEADERS = {
    "Api-Appid": APP_ID,
    "Api-Key": API_KEY,
}

# --- Configuración Passkit ---
PASSKIT_PROGRAM_ID = os.getenv("PASSKIT_PROGRAM_ID", "43BgitIB5LKFIAtREfhN5l")
PASSKIT_API_KEY = os.getenv("PASSKIT_API_KEY")
PASSKIT_SECRET_KEY = os.getenv("PASSKIT_SECRET_KEY")


def extract_contact_id(url_or_id: str) -> str:
    """Extrae el ID numérico del contacto."""
    match = re.search(r"id=(\d+)", url_or_id)
    if match:
        return match.group(1)
    if url_or_id.strip().isdigit():
        return url_or_id.strip()
    raise ValueError(f"No se pudo extraer un ID válido de: {url_or_id}")


def get_contact_data(contact_id: str) -> dict:
    """Obtiene los datos completos del contacto desde la API de Ontraport."""
    url = f"{API_BASE_URL}/Contacts"
    params = {"id": contact_id}
    res = requests.get(url, headers=API_HEADERS, params=params)

    if res.status_code == 404:
        url = f"{API_BASE_URL}/Contact"
        res = requests.get(url, headers=API_HEADERS, params=params)

    res.raise_for_status()

    raw_data = res.json().get("data")
    if isinstance(raw_data, list):
        if not raw_data:
            raise ValueError(f"No se encontró el contacto con ID {contact_id}.")
        return raw_data[0]
    elif isinstance(raw_data, dict):
        return raw_data
    raise ValueError(f"Formato de respuesta inesperado: {raw_data}")


def download_and_convert(image_url: str) -> tuple[io.BytesIO, str]:
    """Descarga la imagen WebP y la convierte a JPEG en memoria."""
    print(f"-> Descargando WebP original: {image_url}")
    res = requests.get(image_url)
    res.raise_for_status()

    img = Image.open(io.BytesIO(res.content))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGB")

    jpeg_buffer = io.BytesIO()
    img.save(jpeg_buffer, format="JPEG", quality=95)
    jpeg_buffer.seek(0)

    original_filename = image_url.split("/")[-1].split("?")[0]
    base_name = re.sub(r"\.webp$", "", original_filename, flags=re.IGNORECASE)
    jpeg_filename = f"{base_name}.jpg"

    return jpeg_buffer, jpeg_filename


def upload_jpeg(jpeg_bytes: io.BytesIO, filename: str) -> str:
    """Sube el JPEG convertido a /Carousel/upload y devuelve la nueva URL en i.ontraport.com."""
    upload_url = f"https://app.ontraport.com/Carousel/upload?aid={AID}"

    headers = {
        "accept": "*/*",
        "csrf": CSRF,
        "cookie": COOKIE,
        "origin": "https://app.ontraport.com",
        "referer": "https://app.ontraport.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
    }

    files = {
        "type": (None, "1"),
        "imageUploadTagData": (None, f"0:{FIELD_IMAGE}"),
        "thefile": (filename, jpeg_bytes, "image/jpeg"),
    }

    res = requests.post(upload_url, headers=headers, files=files)
    res.raise_for_status()

    res_json = res.json()
    file_data = res_json.get("data", {}).get("file_data", {})
    new_url = file_data.get("URL")

    if not new_url:
        raise ValueError(f"No se encontró la clave URL en la respuesta del servidor: {res_json}")

    return new_url


def update_contact_image(contact_id: str, new_image_url: str):
    """Actualiza y guarda el contacto asignando el nuevo enlace JPEG."""
    url = "https://app.ontraport.com/Objects/update"

    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded",
        "csrf": CSRF,
        "cookie": COOKIE,
        "origin": "https://app.ontraport.com",
        "referer": "https://app.ontraport.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }

    payload = {
        "_startOfResource": "1",
        "objectID": "0",
        "id": contact_id,
        FIELD_IMAGE: new_image_url,
        "_endOfResource": "1",
    }

    res = requests.post(url, headers=headers, data=payload)
    res.raise_for_status()
    return res.json()


def trigger_passkit_update(contact_id: str):
    """Agrega la categoría/etiqueta 927 para disparar la actualización hacia Passkit."""
    url = "https://app.ontraport.com/Objects/update"

    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded",
        "csrf": CSRF,
        "cookie": COOKIE,
        "origin": "https://app.ontraport.com",
        "referer": "https://app.ontraport.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }

    payload = {
        "_startOfResource": "1",
        "objectID": "0",
        "__opbuildDate": "1793039495",
        "id": contact_id,
        "subActions[contact_cat][action]": "add",
        "subActions[contact_cat][id]": "927",
        "_endOfResource": "1",
    }

    res = requests.post(url, headers=headers, data=payload)
    res.raise_for_status()
    return res.json()


def generate_passkit_jwt() -> str:
    """Genera el token JWT firmado requerido por la API de Passkit."""
    if not PASSKIT_API_KEY or not PASSKIT_SECRET_KEY:
        raise ValueError("Faltan configurar PASSKIT_API_KEY o PASSKIT_SECRET_KEY en el archivo .env")

    now = int(time.time())
    payload = {
        "uid": PASSKIT_API_KEY,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, PASSKIT_SECRET_KEY, algorithm="HS256")


def get_passkit_member_url(email: str) -> str:
    """Busca el miembro en Passkit por email y genera la URL del perfil."""
    url = f"https://api.pub2.passkit.io/members/member/list/{PASSKIT_PROGRAM_ID}"

    token = generate_passkit_jwt()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = {
        "programId": PASSKIT_PROGRAM_ID,
        "filters": {
            "limit": 10,
            "offset": 0,
            "filterGroups": [
                {
                    "condition": "AND",
                    "fieldFilters": [
                        {
                            "filterField": "email",
                            "filterValue": email,
                            "filterOperator": "eq",
                        }
                    ],
                }
            ],
            "orderBy": "created",
            "orderAsc": False,
        },
    }

    res = requests.post(url, headers=headers, json=payload)
    res.raise_for_status()

    data = res.json()
    result = data.get("result", {})
    member_id = result.get("id")

    if not member_id:
        raise ValueError(f"No se encontró ningún miembro con el correo {email}. Respuesta: {data}")

    return f"https://app.passkit.com/app/membership/{PASSKIT_PROGRAM_ID}/members/{member_id}"


def ask_confirmation(prompt_text: str) -> bool:
    """Pregunta interactiva [y]/[n]."""
    while True:
        choice = input(f"{prompt_text} [y]/[n]: ").strip().lower()
        if choice in ("y", "yes", "s", "si", "sí"):
            return True
        elif choice in ("n", "no"):
            return False
        print("Opción no válida. Por favor escribe 'y' o 'n'.")


def process(link_or_id: str):
    contact_id = extract_contact_id(link_or_id)
    print(f"\n[+] Procesando Contacto ID: {contact_id}")

    # 1. Obtener datos del contacto (email e imagen)
    contact = get_contact_data(contact_id)
    email = contact.get("email")
    image_val = contact.get(FIELD_IMAGE)

    print(f"-> Email del contacto: {email if email else 'No asignado'}")

    image_updated = False

    # 2. Manejo condicional de la imagen
    if not image_val or not str(image_val).strip():
        print(f"[-] AVISO: El contacto {contact_id} no tiene foto de perfil.")
        print("-> Saltando directo a Passkit...")
    elif str(image_val).lower().endswith(".jpeg") or str(image_val).lower().endswith(".jpg"):
        print(f"-> La imagen ya se encuentra en formato JPEG: {image_val}")
        print("-> Saltando directo a Passkit...")
    else:
        current_url = image_val if image_val.startswith("http") else f"https://i.ontraport.com/{image_val}"
        print(f"-> Imagen encontrada: {current_url}")

        try:
            # Descargar y convertir
            jpeg_bytes, new_filename = download_and_convert(current_url)

            # Subir a Ontraport
            print(f"-> Subiendo archivo: {new_filename} ...")
            new_url = upload_jpeg(jpeg_bytes, filename=new_filename)
            print(f"-> Subida exitosa. Nueva URL: {new_url}")

            # Guardar en contacto
            print(f"-> Actualizando contacto con el nuevo JPEG...")
            update_contact_image(contact_id, new_url)
            print(f"[✓] Imagen actualizada a JPEG con éxito.")
            image_updated = True
        except Exception as e:
            print(f"[-] Error durante el proceso de la imagen: {e}")

    # 3. Passkit Update (ÚNICAMENTE si se procesó y guardó una imagen JPEG)
    if image_updated:
        print()
        if ask_confirmation("¿Aplicar el Passkit - Update?"):
            print(f"-> Disparando actualización a Passkit (agregando categoría 927)...")
            trigger_passkit_update(contact_id)
            print(f"[✓] Passkit actualizado correctamente para el contacto {contact_id}.")
        else:
            print(f"[-] Actualización a Passkit omitida.")

    # 4. Enlace de Passkit (se pregunta siempre que haya email)
    print()
    if ask_confirmation("¿Deseas generar el enlace de miembro Passkit?"):
        if not email:
            print("[-] No se puede generar el enlace: el contacto no tiene un correo asignado.")
        else:
            try:
                print(f"-> Consultando miembro en Passkit con email {email}...")
                member_url = get_passkit_member_url(email)
                print(f"\n🔗 [ENLACE DE MIEMBRO PASSKIT]:\n{member_url}\n")
            except Exception as e:
                print(f"[-] Error al generar el enlace de Passkit: {e}")
    else:
        print(f"[-] Generación de enlace de Passkit omitida.")

    print(f"[✓] Proceso finalizado para el contacto {contact_id}.\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_link = sys.argv[1]
    else:
        target_link = input("Pega el enlace del contacto: ")

    process(target_link)