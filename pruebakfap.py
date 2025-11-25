import telegram
import cloudscraper # CAMBIO IMPORTANTE
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
TOKEN_RESPALDO = '8120664964:AAEnz4LveHyJaQcc7PHBDJg5RBDQ5bfk_FI'
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', TOKEN_RESPALDO)

BASE_URL = "https://idolfap.com"

# CREAMOS EL SCRAPER QUE SE SALTA PROTECCIONES
# Esto simula ser un navegador Chrome real para engañar a la página
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})

# --- 1. SERVIDOR WEB (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "El bot está vivo y corriendo."

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- 2. FUNCIÓN DE SCRAPING: Obtener enlace ---
def obtener_enlace_aleatorio(idolo_nombre: str) -> Optional[str]:
    url_idolo = f"{BASE_URL}/idols/{idolo_nombre.lower()}/"
    print(f"Rascando la URL de publicaciones: {url_idolo}", flush=True) # flush=True fuerza que salga en el log

    try:
        # USAMOS SCRAPER EN LUGAR DE REQUESTS
        response = scraper.get(url_idolo, timeout=15)
        
        # Si nos da error 403 o 503, lanzará excepción
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        post_links = []
        
        for article_tag in soup.find_all('article', class_='post'):
            a_tag = article_tag.find('a', href=True)
            if a_tag and '/post/' in a_tag['href']:
                post_links.append(a_tag['href'])

        if not post_links:
            print(f"DEBUG: HTML recibido pero no hay posts. Título de página: {soup.title.string if soup.title else 'Sin título'}", flush=True)
            return None

        enlace_relativo_aleatorio = random.choice(post_links)
        return BASE_URL + enlace_relativo_aleatorio

    except Exception as e:
        print(f"Error al rascar la página del ídolo ({url_idolo}): {e}", flush=True)
        return None

# --- 3. FUNCIÓN DE SCRAPING: Obtener archivo ---
def obtener_url_archivo(url_publicacion: str) -> str | None:
    print(f"Rascando archivo en: {url_publicacion}", flush=True)
    try:
        # USAMOS SCRAPER
        response = scraper.get(url_publicacion, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1) Video MP4
        for source in soup.find_all("source"):
            src = source.get("src")
            if src and ".mp4" in src:
                if src.startswith("//"): src = "https:" + src
                elif src.startswith("/"): src = BASE_URL + src
                print(f"Encontrado MP4: {src}", flush=True)
                return src

        # 2) Poster
        for video in soup.find_all("video"):
            poster = video.get("data-poster") or video.get("poster")
            if poster and "/files/" in poster:
                if poster.startswith("//"): poster = "https:" + poster
                elif poster.startswith("/"): poster = BASE_URL + poster
                print(f"Encontrado Poster: {poster}", flush=True)
                return poster

        # 3) Imágenes
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and "/files/" in src:
                if src.startswith("//"): src = "https:" + src
                elif src.startswith("/"): src = BASE_URL + src
                print(f"Encontrada IMG: {src}", flush=True)
                return src
        
        print("DEBUG: No se encontraron multimedia en el post.", flush=True)
        return None
    except Exception as e:
        print(f"Error obteniendo archivo: {e}", flush=True)
        return None

# --- 4. COMANDO ---
async def imagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usa: /imagen <nombre>")
        return

    idolo_nombre = context.args[0]
    await update.message.reply_text(f"Buscando a **{idolo_nombre.capitalize()}**...", parse_mode=telegram.constants.ParseMode.MARKDOWN)

    url_archivo = None
    url_publicacion = None
    MAX_ATTEMPTS = 5
    
    for attempt in range(MAX_ATTEMPTS):
        url_publicacion = await asyncio.to_thread(obtener_enlace_aleatorio, idolo_nombre)
        if not url_publicacion:
            # Si falla el primer paso, esperamos un poco más
            await asyncio.sleep(2)
            continue
            
        url_archivo = await asyncio.to_thread(obtener_url_archivo, url_publicacion)
        if url_archivo: 
            break
        await asyncio.sleep(1)
        
    if not url_archivo:
        await update.message.reply_text("❌ Render fue bloqueado o no encontró contenido. Revisa los logs.")
        return

    try:
        # Descargamos también con scraper
        file_content_response = await asyncio.to_thread(scraper.get, url_archivo, timeout=30)
        file_content_response.raise_for_status()
        file_bytes = file_content_response.content
        
        file_extension = url_archivo.lower().split('.')[-1]
        filename = f'{idolo_nombre}.{file_extension}'

        if file_extension in ('jpg', 'jpeg', 'png'):
            await update.message.reply_photo(photo=InputFile(file_bytes, filename=filename), caption=f"Fuente: {url_publicacion}")
        elif file_extension in ('webp', 'gif', 'mp4', 'webm'):
            await update.message.reply_document(document=InputFile(file_bytes, filename=filename), caption=f"Fuente: {url_publicacion}")
        else:
             await update.message.reply_text("Formato no compatible.")

    except Exception as e:
        await update.message.reply_text(f"Error al enviar: {e}")

# --- 5. INICIO ---
def main() -> None:
    if not TELEGRAM_TOKEN:
        print("ERROR: No hay token.", flush=True)
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("imagen", imagen_command))
    
    print("Bot iniciado con CloudScraper.", flush=True)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    keep_alive()
    main()
