import telegram
from curl_cffi import requests # ESTA ES LA NUEVA LIBRERÍA POTENTE
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

# --- 1. SERVIDOR WEB (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "El bot está vivo."

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- HELPER: PETICIÓN SEGURA ---
def hacer_peticion_segura(url):
    """
    Usa curl_cffi para imitar un navegador Chrome real a nivel TLS.
    Esto es lo que evita el error 403.
    """
    # impersonate="chrome110" imita exactamente las firmas digitales de Chrome
    return requests.get(url, impersonate="chrome110", timeout=15)

# --- 2. FUNCIÓN DE SCRAPING: Obtener enlace ---
def obtener_enlace_aleatorio(nombre: str, seccion: str = "idols") -> Optional[str]:
    # Los ídolos/grupos van en minúscula; los creadores respetan mayúsculas.
    nombre_url = nombre if seccion == "creator" else nombre.lower()
    url_idolo = f"{BASE_URL}/{seccion}/{nombre_url}/"
    print(f"Rascando URL: {url_idolo}", flush=True)

    try:
        # Usamos la función segura
        response = hacer_peticion_segura(url_idolo)
        
        # Si sigue dando 403, esto lanzará el error para verlo en el log
        if response.status_code == 403:
            print("CRÍTICO: Error 403. Cloudflare sigue bloqueando la IP de Render.", flush=True)
            return None
            
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        post_links = []
        
        for article_tag in soup.find_all('article', class_='post'):
            a_tag = article_tag.find('a', href=True)
            if a_tag and '/post/' in a_tag['href']:
                post_links.append(a_tag['href'])

        if not post_links:
            print(f"No se encontraron posts. Status: {response.status_code}", flush=True)
            return None

        enlace_relativo_aleatorio = random.choice(post_links)
        return BASE_URL + enlace_relativo_aleatorio

    except Exception as e:
        print(f"Error general buscando ídolo: {e}", flush=True)
        return None

def _normalizar_url(u: str) -> str:
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE_URL + u
    return u

# --- 3. FUNCIÓN DE SCRAPING: Obtener TODOS los archivos (soporta carruseles) ---
def obtener_urls_archivos(url_publicacion: str) -> list:
    """Devuelve TODAS las URLs de multimedia de un post, en orden y sin duplicados."""
    print(f"Buscando multimedia en: {url_publicacion}", flush=True)
    urls = []

    def _add(u):
        # Descartar miniaturas/previews: los reales van en /files/src/,
        # las previews en /files/thumb/.
        if u and "/files/thumb/" not in u and u not in urls:
            urls.append(u)

    try:
        response = hacer_peticion_segura(url_publicacion)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # 1) Videos MP4
        for source in soup.find_all("source"):
            src = source.get("src")
            if src and ".mp4" in src:
                _add(_normalizar_url(src))

        # 2) Posters de video
        for video in soup.find_all("video"):
            poster = video.get("data-poster") or video.get("poster")
            if poster and "/files/" in poster:
                _add(_normalizar_url(poster))

        # 3) Imágenes
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and "/files/" in src:
                _add(_normalizar_url(src))

        return urls
    except Exception as e:
        print(f"Error buscando archivos: {e}", flush=True)
        return urls

# Compatibilidad: devuelve solo el primer archivo (flujo aleatorio normal).
def obtener_url_archivo(url_publicacion: str) -> str | None:
    urls = obtener_urls_archivos(url_publicacion)
    return urls[0] if urls else None

# --- 4a. FUNCIÓN DEL BOT: Manejar el comando /monkeyfap_ayuda ---
async def ayuda_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de comandos disponibles y cómo usarlos."""
    texto_ayuda = (
        "🐵 *MonkeyFap - Ayuda*\n\n"
        "Estos son los comandos disponibles:\n\n"
        "📷 */imagen <nombre>*\n"
        "Busca y envía contenido aleatorio del ídolo indicado.\n"
        "_Ejemplo:_ `/imagen mbnu`\n\n"
        "👥 */grupo <nombre>*\n"
        "Busca y envía contenido aleatorio de un grupo.\n"
        "_Ejemplo:_ `/grupo aespa`\n\n"
        "🎨 */creador <nombre>*\n"
        "Busca y envía contenido aleatorio de un creador.\n"
        "_Ejemplo:_ `/creador Izland`\n"
        "⚠️ El nombre del creador respeta MAYÚSCULAS/minúsculas.\n\n"
        "🧪 */imagen prueba*\n"
        "Prueba un post fijo con carrusel (envía todos sus archivos).\n\n"
        "❓ */monkeyfap_ayuda*\n"
        "Muestra este mensaje de ayuda.\n\n"
        "ℹ️ Escribe el nombre en una sola palabra, sin espacios."
    )
    await update.message.reply_text(
        texto_ayuda,
        parse_mode=telegram.constants.ParseMode.MARKDOWN,
    )


# --- HELPER: enviar un archivo multimedia a Telegram según su extensión ---
async def enviar_media(update: Update, url_archivo: str, nombre_base: str, caption: str) -> bool:
    """Descarga y envía un archivo. Devuelve True si se envió."""
    file_response = await asyncio.to_thread(hacer_peticion_segura, url_archivo)
    file_response.raise_for_status()
    file_bytes = file_response.content

    file_extension = url_archivo.lower().split('.')[-1]
    filename = f'{nombre_base}.{file_extension}'

    if file_extension in ('jpg', 'jpeg', 'png'):
        await update.message.reply_photo(photo=InputFile(file_bytes, filename=filename), caption=caption)
        return True
    elif file_extension in ('webp', 'gif', 'mp4', 'webm'):
        await update.message.reply_document(document=InputFile(file_bytes, filename=filename), caption=caption)
        return True
    return False


# --- 4. FUNCIÓN NÚCLEO: buscar y enviar (usada por /imagen, /grupo y /creador) ---
async def buscar_y_enviar(update: Update, context: ContextTypes.DEFAULT_TYPE, seccion: str = "idols") -> None:
    if not context.args:
        await update.message.reply_text("Usa: /imagen <nombre>, /grupo <nombre> o /creador <nombre>")
        return

    idolo_nombre = context.args[0]
    # Mensaje inicial
    msg = await update.message.reply_text(f"🔍 Buscando a **{idolo_nombre.capitalize()}**...", parse_mode=telegram.constants.ParseMode.MARKDOWN)

    url_archivo = None
    url_publicacion = None
    MAX_ATTEMPTS = 4 # Bajamos intentos para no saturar

    for attempt in range(MAX_ATTEMPTS):
        url_publicacion = await asyncio.to_thread(obtener_enlace_aleatorio, idolo_nombre, seccion)
        if not url_publicacion:
            await asyncio.sleep(2)
            continue
            
        url_archivo = await asyncio.to_thread(obtener_url_archivo, url_publicacion)
        if url_archivo: 
            break
        await asyncio.sleep(1)
        
    if not url_archivo:
        await msg.edit_text("❌ No se pudo descargar nada. La página está bloqueando los servidores de Render (Error 403).")
        return

    try:
        # Descarga final usando también curl_cffi para evitar bloqueo en la imagen
        await msg.edit_text("⬇️ Descargando y enviando...")
        enviado = await enviar_media(update, url_archivo, idolo_nombre, caption=f"Fuente: {url_publicacion}")
        if not enviado:
            await msg.edit_text("Formato desconocido.")

    except Exception as e:
        await msg.edit_text(f"Error al enviar: {e}")


# --- 4b. PRUEBA HARDCODEADA: /imagen prueba (post con carrusel) ---
POST_PRUEBA = "https://idolfap.com/post/151586/"

async def prueba_carrusel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extrae y envía TODOS los archivos del post de prueba (soporte carrusel)."""
    msg = await update.message.reply_text("🧪 Probando post hardcodeado (carrusel)...")

    urls = await asyncio.to_thread(obtener_urls_archivos, POST_PRUEBA)
    if not urls:
        await msg.edit_text("❌ No se encontró multimedia en el post de prueba (¿403 de Cloudflare?).")
        return

    await msg.edit_text(f"✅ Encontré {len(urls)} archivo(s). Enviando...")

    # DEBUG: mostrar la lista de URLs detectadas para depurar duplicados/previews
    listado = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1))
    await update.message.reply_text(f"🔎 URLs detectadas:\n{listado}"[:4000])

    enviados = 0
    for i, u in enumerate(urls, 1):
        try:
            if await enviar_media(update, u, f"prueba_{i}", caption=f"[{i}/{len(urls)}] {u}"):
                enviados += 1
        except Exception as e:
            print(f"Error enviando {u}: {e}", flush=True)

    if enviados == 0:
        await msg.edit_text("❌ Se encontraron URLs pero no se pudieron enviar.")
    else:
        await msg.edit_text(f"✅ Enviados {enviados}/{len(urls)} archivo(s) del carrusel.")


# --- 4c. COMANDOS: cada uno usa su sección del sitio ---
async def imagen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Caso especial de prueba: /imagen prueba -> post hardcodeado con carrusel
    if context.args and context.args[0].lower() == "prueba":
        await prueba_carrusel(update, context)
        return
    await buscar_y_enviar(update, context, seccion="idols")

async def grupo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await buscar_y_enviar(update, context, seccion="idols")

async def creador_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await buscar_y_enviar(update, context, seccion="creator")

# --- 5. INICIO ---
def main() -> None:
    if not TELEGRAM_TOKEN:
        print("ERROR: No hay token.", flush=True)
        return

    # concurrent_updates(True) permite procesar varias peticiones a la vez
    # (cada update se maneja como una tarea independiente, no en serie).
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    application.add_handler(CommandHandler("imagen", imagen_command))
    application.add_handler(CommandHandler("grupo", grupo_command))
    application.add_handler(CommandHandler("creador", creador_command))
    application.add_handler(CommandHandler("monkeyfap_ayuda", ayuda_command))

    print("Bot iniciado con CURL_CFFI (Anti-Bloqueo). Comandos: /imagen, /grupo, /creador, /monkeyfap_ayuda", flush=True)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    keep_alive()
    main()
