import io
import os
import re
import sys
import time
import jwt
import requests
import pandas as pd
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
    match = re.search(r"id=(\d+)", str(url_or_id))
    if match:
        return match.group(1)
    cleaned = str(url_or_id).strip()
    if cleaned.isdigit():
        return cleaned
    raise ValueError(f"No se pudo extraer un ID válido de: {url_or_id}")


def get_contact_data(contact_id: str) -> dict:
    """Obtiene los datos del contacto desde la API de Ontraport."""
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
    """Sube el JPEG convertido a /Carousel/upload y devuelve la nueva URL de forma robusta."""
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

    new_url = None

    # Extracción segura ante cualquier formato de res.json()
    try:
        res_json = res.json()
        if isinstance(res_json, dict):
            data_val = res_json.get("data")
            if isinstance(data_val, dict):
                file_data = data_val.get("file_data")
                if isinstance(file_data, dict):
                    new_url = file_data.get("URL") or file_data.get("url")
                if not new_url:
                    new_url = data_val.get("URL") or data_val.get("url")
            elif isinstance(data_val, str) and "http" in data_val:
                new_url = data_val

            if not new_url:
                new_url = res_json.get("URL") or res_json.get("url")
    except Exception:
        pass

    # Si no vino estructurado en JSON, extraer con regex directo del texto
    if not new_url:
        match = re.search(r"https://i\.ontraport\.com/[^\s\"'<>]+", res.text)
        if match:
            new_url = match.group(0)

    if not new_url:
        raise ValueError(f"No se pudo extraer la nueva URL del servidor. Respuesta: {res.text}")

    # Limpiar posibles barras invertidas devueltas por JSON
    new_url = str(new_url).replace("\\/", "/")
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
    """Agrega la categoría 927 para disparar la actualización a Passkit."""
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
    """Genera el token JWT firmado para Passkit."""
    if not PASSKIT_API_KEY or not PASSKIT_SECRET_KEY:
        raise ValueError("Falta PASSKIT_API_KEY o PASSKIT_SECRET_KEY en el archivo .env")

    now = int(time.time())
    payload = {
        "uid": PASSKIT_API_KEY,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, PASSKIT_SECRET_KEY, algorithm="HS256")


def get_passkit_member_url(email: str) -> str:
    """Busca el miembro en Passkit y genera el enlace del perfil."""
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
        raise ValueError(f"No se encontró ningún miembro con el correo {email}.")

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


def process_single_contact(link_or_id: str, auto_confirm: bool = False) -> tuple[bool, str]:
    """
    Procesa un contacto individual.
    Retorna (éxito: bool, motivo: str).
    """
    contact_id = extract_contact_id(link_or_id)
    print(f"\n==========================================")
    print(f"[+] Procesando Contacto ID: {contact_id}")
    print(f"==========================================")

    # 1. Obtener datos
    try:
        contact = get_contact_data(contact_id)
    except Exception as e:
        msg = f"Error al consultar contacto en Ontraport: {e}"
        print(f"[-] {msg}")
        return False, msg

    email = contact.get("email")
    image_val = contact.get(FIELD_IMAGE)
    print(f"-> Email: {email if email else 'No asignado'}")

    image_updated = False
    skip_reason = None

    # 2. Validar imagen
    if not image_val or not str(image_val).strip():
        skip_reason = "No tiene foto de perfil"
        print(f"[-] AVISO: {skip_reason}. Saltando conversión y Passkit Update...")
    elif str(image_val).lower().endswith(".jpeg") or str(image_val).lower().endswith(".jpg"):
        skip_reason = f"La foto ya es JPEG ({image_val})"
        print(f"-> {skip_reason}. Saltando conversión y Passkit Update...")
    else:
        current_url = image_val if image_val.startswith("http") else f"https://i.ontraport.com/{image_val}"
        print(f"-> Imagen encontrada: {current_url}")

        # 3. Conversión y subida
        try:
            jpeg_bytes, new_filename = download_and_convert(current_url)
            print(f"-> Subiendo archivo: {new_filename} ...")
            new_url = upload_jpeg(jpeg_bytes, filename=new_filename)
            print(f"-> Subida exitosa: {new_url}")

            print(f"-> Guardando en contacto...")
            update_contact_image(contact_id, new_url)
            print(f"[✓] Imagen actualizada a JPEG con éxito.")
            image_updated = True
        except Exception as e:
            msg = f"Error al convertir/subir la imagen: {e}"
            print(f"[-] {msg}")
            return False, msg

    # 4. Actualización a Passkit (solo si se convirtió una imagen con éxito)
    if image_updated:
        apply_update = True if auto_confirm else ask_confirmation("¿Aplicar el Passkit - Update?")
        if apply_update:
            try:
                print(f"-> Disparando actualización a Passkit (categoría 927)...")
                trigger_passkit_update(contact_id)
                print(f"[✓] Passkit actualizado correctamente.")
            except Exception as e:
                print(f"[-] Error al disparar actualización a Passkit: {e}")
        else:
            print(f"[-] Passkit Update omitido.")

    # 5. Enlace de miembro Passkit (siempre disponible si hay correo)
    generate_link = True if auto_confirm else ask_confirmation("¿Deseas generar el enlace de miembro Passkit?")
    if generate_link:
        if email:
            try:
                print(f"-> Consultando miembro en Passkit...")
                member_url = get_passkit_member_url(email)
                print(f"\n🔗 [ENLACE DE MIEMBRO PASSKIT]:\n{member_url}\n")
            except Exception as e:
                print(f"[-] Error al generar enlace de Passkit: {e}")
        else:
            print("[-] Contacto sin correo, enlace omitido.")

    if not image_updated:
        return False, skip_reason

    print(f"[✓] Contacto {contact_id} completado con éxito.")
    return True, "Procesado correctamente"


def process_excel(file_path: str):
    """Lee el Excel y ejecuta el proceso en lote automáticamente con pausa."""
    if not os.path.exists(file_path):
        print(f"Error: No existe el archivo en la ruta '{file_path}'.")
        return

    df = pd.read_excel(file_path)

    # Identificar la columna de contactos
    col_name = None
    for candidate in ["CONTACTS", "contacts", "contacto", "contactos", "link", "url"]:
        for c in df.columns:
            if candidate == str(c).strip().lower():
                col_name = c
                break
        if col_name:
            break

    if not col_name:
        col_name = df.columns[-1]
        print(f"-> No se encontró columna llamada 'CONTACTS', usando: '{col_name}'")

    contact_links = df[col_name].dropna().tolist()
    total = len(contact_links)
    print(f"\n[+] Iniciando proceso de {total} contactos desde '{file_path}'...")

    unsuccessful_records = []
    success_count = 0

    for idx, link in enumerate(contact_links, start=1):
        print(f"\n[{idx}/{total}] Procesando...")
        try:
            contact_id = extract_contact_id(link)
            success, reason = process_single_contact(link, auto_confirm=True)
            if success:
                success_count += 1
            else:
                unsuccessful_records.append({
                    "CONTACT_URL": link,
                    "CONTACT_ID": contact_id,
                    "MOTIVO_FALLO": reason
                })
        except Exception as e:
            unsuccessful_records.append({
                "CONTACT_URL": link,
                "CONTACT_ID": "DESCONOCIDO",
                "MOTIVO_FALLO": str(e)
            })

        # Pausa de 3 segundos entre contactos
        if idx < total:
            print("-> Esperando 3 segundos antes del siguiente contacto...")
            time.sleep(3)

    # Guardar reporte de contactos no exitosos
    output_filename = "contactos_no_exitosos.xlsx"
    if unsuccessful_records:
        df_failed = pd.DataFrame(unsuccessful_records)
        df_failed.to_excel(output_filename, index=False)
        print(f"\n==========================================")
        print(f"[!] REPORTE FINALIZADO:")
        print(f"    - Exitosos: {success_count}/{total}")
        print(f"    - No exitosos: {len(unsuccessful_records)}/{total}")
        print(f"    - Archivo generado con errores: {output_filename}")
        print(f"==========================================\n")
    else:
        print(f"\n[✓] ¡Excelente! Los {total} contactos fueron procesados con éxito. No hubo fallos.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        param = sys.argv[1]
        if param.endswith(".xlsx") or param.endswith(".xls"):
            process_excel(param)
        else:
            process_single_contact(param, auto_confirm=False)
    else:
        print("¿Qué deseas hacer?")
        print("1. Procesar un archivo Excel")
        print("2. Procesar un contacto individual")
        opcion = input("Elige una opción (1 o 2): ").strip()

        if opcion == "1":
            default_path = "OP Links afectados de Passkit.xlsx"
            path_input = input(f"Ingresa la ruta del archivo Excel [Enter para '{default_path}']: ").strip()
            file_to_run = path_input if path_input else default_path
            process_excel(file_to_run)
        else:
            target_link = input("Pega el enlace del contacto: ").strip()
            process_single_contact(target_link, auto_confirm=False)