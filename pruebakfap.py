import telegram
import requests
from bs4 import BeautifulSoup
import random
import asyncio
import os
from threading import Thread
from flask import Flask
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update, InputFile
from typing import Optional

# --- CONFIGURACIÓN ---

# TU TOKEN (El que diste): Se usa como respaldo si no hay variables de entorno
TOKEN_RESPALDO = '8120664964:AAEnz4LveHyJaQcc7PHBDJg5RBDQ5bfk_FI'

# Busca la variable de entorno (para Render). Si no existe, usa el TOKEN_RESPALDO (para tu PC)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', TOKEN_RESPALDO)

# Configuración Anti-Proxy y Headers de navegador
PROXIES_OFF = {'http': None, 'https': None}
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
BASE_URL = "https://idolfap.com"


# --- 1. SERVIDOR WEB (KEEP ALIVE) PARA RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "El bot está vivo y corriendo."

def run():
    # Render asigna un puerto en la variable PORT, si no hay, usa el 8080
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()


# --- 2. FUNCIÓN DE SCRAPING: Obtener un enlace de publicación aleatorio ---
def obtener_enlace_aleatorio(idolo_nombre: str) -> Optional[str]:
    """Busca <article class="post"> y extrae un enlace aleatorio /post/XXXXX/."""
    url_idolo = f"{BASE_URL}/idols/{idolo_nombre.lower()}/"
    
    print(f"Rascando la URL de publicaciones: {url_idolo}")

    try:
        response = requests.get(url_idolo, headers=HEADERS, proxies=PROXIES_OFF, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        post_links = []
        
        # Búsqueda basada en la inspección: <article class="post">
        for article_tag in soup.find_all('article', class_='post'):
            a_tag = article_tag.find('a', href=True)
            
            if a_tag and '/post/' in a_tag['href']:
                post_links.append(a_tag['href'])

        if not post_links:
            print("No se encontraron enlaces de publicaciones válidos.")
            return None

        enlace_relativo_aleatorio = random.choice(post_links)
        enlace_completo_aleatorio = BASE_URL + enlace_relativo_aleatorio
        
        return enlace_completo_aleatorio

    except requests.exceptions.RequestException as e:
        print(f"Error al rascar la página del ídolo: {e}")
        return None

# --- 3. FUNCIÓN DE SCRAPING: Obtener la URL directa del archivo ---
def obtener_url_archivo(url_publicacion: str) -> str | None:
    print(f"Rascando archivo en: {url_publicacion}")

    try:
        response = requests.get(url_publicacion, headers=HEADERS, proxies=PROXIES_OFF, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # ==========================================================
        # 1) PRIORIDAD MÁXIMA: VIDEO .MP4
        # ==========================================================
        for source in soup.find_all("source"):
            src = source.get("src")
            if not src:
                continue

            if ".mp4" in src:
                # Normalizar
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = BASE_URL + src

                print("Detectado VIDEO MP4:", src)
                return src

        # ==========================================================
        # 2) POSTER de VIDEO (si no hay mp4)
        # ==========================================================
        for video in soup.find_all("video"):
            poster = video.get("data-poster") or video.get("poster")
            if poster and "/files/" in poster:
                if poster.startswith("//"):
                    poster = "https:" + poster
                elif poster.startswith("/"):
                    poster = BASE_URL + poster

                print("Detectado POSTER:", poster)
                return poster

        # ==========================================================
        # 3) IMÁGENES REALES (último recurso)
        # ==========================================================
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            if "/files/" in src:
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = BASE_URL + src

                print("Detectada IMG:", src)
                return src

        print("No hay imágenes ni videos reales en este post.")
        return None

    except Exception as e:
        print(f"Error al obtener archivo: {e}")
        return None

# --- 4. FUNCIÓN DEL BOT: Manejar el comando /imagen ---
async def imagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /imagen <nombre> con lógica de re-intento y descarga de archivos."""
    if not context.args:
        await update.message.reply_text("Por favor, usa el formato: /imagen <nombre_del_idolo>")
        return

    idolo_nombre = context.args[0]
    await update.message.reply_text(f"Buscando una imagen aleatoria de **{idolo_nombre.capitalize()}**...", parse_mode=telegram.constants.ParseMode.MARKDOWN)

    url_archivo = None
    url_publicacion = None
    MAX_ATTEMPTS = 5
    
    # Bucle de re-intento para evitar posts premium/inaccesibles
    for attempt in range(MAX_ATTEMPTS):
        url_publicacion = await asyncio.to_thread(obtener_enlace_aleatorio, idolo_nombre)

        if not url_publicacion:
            break 
        
        url_archivo = await asyncio.to_thread(obtener_url_archivo, url_publicacion)
        
        if url_archivo:
            print(f"Éxito en el intento {attempt + 1}: {url_archivo}")
            break 
        
        if attempt < MAX_ATTEMPTS - 1:
            await update.message.reply_text(f"⚠️ Intento {attempt + 1}/{MAX_ATTEMPTS}: Publicación inaccesible o Premium. Re-intentando...")
            await asyncio.sleep(1) 

    if not url_archivo:
        await update.message.reply_text(f"❌ Fallamos después de {MAX_ATTEMPTS} intentos. No se encontró contenido público.")
        return

    # Descargar el archivo binario y enviarlo a Telegram
    try:
        file_content_response = await asyncio.to_thread(
            requests.get, url_archivo, headers=HEADERS, proxies=PROXIES_OFF, timeout=30
        )
        file_content_response.raise_for_status() 
        file_bytes = file_content_response.content 
        
        url_lower = url_archivo.lower()
        file_extension = url_lower.split('.')[-1]
        filename = f'{idolo_nombre}.{file_extension}'

        # Lógica de envío basada en extensión
        if file_extension in ('jpg', 'jpeg', 'png'):
            await update.message.reply_photo(
                photo=InputFile(file_bytes, filename=filename), 
                caption=f"¡Aquí tienes a {idolo_nombre.capitalize()}! (Fuente: {url_publicacion})",
            )
        elif file_extension in ('webp', 'gif', 'mp4', 'webm'):
            await update.message.reply_document(
                document=InputFile(file_bytes, filename=filename),
                caption=f"¡Aquí tienes el archivo animado/video de {idolo_nombre.capitalize()}! (Fuente: {url_publicacion})",
            )
        else:
             await update.message.reply_text(f"El archivo encontrado tiene un formato no compatible: {url_archivo}")

    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f"❌ Error al descargar el archivo. Detalles: {e}")
    except telegram.error.BadRequest as e:
        print(f"Error de Telegram: {e}")
        await update.message.reply_text(f"Ocurrió un error al enviar el archivo.")
    except Exception as e:
        print(f"Error desconocido final: {e}")
        await update.message.reply_text(f"Ocurrió un error desconocido: {e}")


# --- 5. FUNCIÓN PRINCIPAL ---
def main() -> None:
    """Inicia el bot usando la clase Application (v20+)."""
    
    # Verificación simple para evitar errores si el token está vacío
    if not TELEGRAM_TOKEN:
        print("ERROR CRÍTICO: No hay token configurado. Revisa la variable TELEGRAM_TOKEN o TOKEN_RESPALDO.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("imagen", imagen_command))

    print("Bot iniciado correctamente. Envía /imagen <nombre> en Telegram.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    keep_alive() # Inicia el servidor Flask en segundo plano
    main()       # Inicia el bot