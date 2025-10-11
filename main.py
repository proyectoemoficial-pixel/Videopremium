import os
import re
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
PORT = int(os.environ.get("PORT", 8080))

# IDs de los canales privados de contenido
CANAL_PELICULAS_ID = -1002179007284 # Canal de películas
CANAL_SERIES_ID = -1002148331988   # Canal de series

# Variables globales
application = None
bot = None

# Sistema de usuarios
usuarios = {}  # {user_id: {fecha_registro, descargas}}

# Sistema de conteo de descargas
descargas_usuarios = {}  # {user_id: contador_descargas}

def registrar_usuario(user_id):
    """Registra un nuevo usuario"""
    if user_id not in usuarios:
        usuarios[user_id] = {
            'fecha_registro': datetime.now().isoformat(),
            'descargas': 0
        }
        logger.info(f"Nuevo usuario registrado: {user_id}")

def contar_usuarios():
    """Cuenta el total de usuarios registrados"""
    return len(usuarios)

def contar_descarga_usuario(user_id):
    """Incrementa el contador de descargas del usuario"""
    if user_id not in descargas_usuarios:
        descargas_usuarios[user_id] = 0
    descargas_usuarios[user_id] += 1
    
    # Actualizar también en el diccionario de usuarios
    if user_id in usuarios:
        usuarios[user_id]['descargas'] = descargas_usuarios[user_id]
    
    return descargas_usuarios[user_id]

def obtener_descargas_usuario(user_id):
    """Obtiene el número de descargas del usuario"""
    return descargas_usuarios.get(user_id, 0)

def detectar_canal_origen(texto):
    """Detecta de qué canal provienen los enlaces"""
    if str(CANAL_PELICULAS_ID).replace('-100', '') in texto:
        return CANAL_PELICULAS_ID, "🎬 PELÍCULA"
    elif str(CANAL_SERIES_ID).replace('-100', '') in texto:
        return CANAL_SERIES_ID, "📺 SERIE"
    return None, None

async def detectar_enlaces_serie(texto):
    """Detecta múltiples enlaces de canal en un mensaje"""
    enlaces = re.findall(r't\.me/c/[^/\s]+/(\d+)', texto)
    return [int(msg_id) for msg_id in enlaces]

async def manejar_serie_enlaces(update: Update, context: ContextTypes.DEFAULT_TYPE, message_ids, canal_id, tipo_contenido):
    """Procesa una serie basada en múltiples enlaces enviados juntos"""
    user_id = update.message.from_user.id
    total_videos = len(message_ids)
    
    processing_msg = await update.message.reply_text(f"{tipo_contenido} detectada: {total_videos} episodios\n\n🔄 Comenzando envío...")
    
    enviados = 0
    errores = 0
    
    for i, message_id in enumerate(message_ids, 1):
        try:
            if i % 3 == 0 or i == total_videos:
                await processing_msg.edit_text(f"{tipo_contenido} en progreso\n\n"
                                              f"📊 Episodio: {i}/{total_videos}\n"
                                              f"✅ Enviados: {enviados}\n"
                                              f"❌ Errores: {errores}")
            
            try:
                await context.bot.copy_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=canal_id,
                    message_id=message_id,
                    caption=f"{tipo_contenido} - Episodio {i}/{total_videos}"
                )
                enviados += 1
                logger.info(f"Serie: Episodio {i} enviado (ID: {message_id})")
                
            except Exception as copy_error:
                try:
                    await context.bot.forward_message(
                        chat_id=update.effective_chat.id,
                        from_chat_id=canal_id,
                        message_id=message_id
                    )
                    enviados += 1
                    logger.info(f"Serie: Episodio {i} forwardeado (ID: {message_id})")
                except:
                    errores += 1
                    logger.error(f"Serie: Error enviando episodio {i} (ID: {message_id})")
            
            await asyncio.sleep(1.2)
            
        except Exception as e:
            errores += 1
            logger.error(f"Error general enviando episodio {i}: {e}")
    
    contar_descarga_usuario(user_id)
    
    await processing_msg.edit_text(f"🎉 ¡{tipo_contenido} completada!\n\n"
                                  f"📺 Total episodios: {total_videos}\n"
                                  f"✅ Enviados exitosamente: {enviados}\n"
                                  f"❌ Errores: {errores}\n\n"
                                  f"🎬 ¡Disfruta tu contenido!")

async def keep_alive():
    """Mantiene el servidor activo haciendo ping cada 5 minutos"""
    while True:
        try:
            await asyncio.sleep(300)
            if WEBHOOK_URL:
                async with aiohttp.ClientSession() as session:
                    ping_url = f"{WEBHOOK_URL}/health"
                    async with session.get(ping_url, timeout=10) as response:
                        logger.info(f"Keep-alive ping: {response.status}")
        except Exception as e:
            logger.error(f"Error en keep-alive: {e}")

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    registrar_usuario(user_id)
    
    descargas = obtener_descargas_usuario(user_id)
    
    await update.message.reply_text(f"""👋 ¡Bienvenido a nuestro bot!

@Hsitotvbot

⬇️ Aquí podrás ver tu contenido favorito como pelis y series

✨ ¿Cómo funciona?
Pega el enlace del canal y envíanoslo

📊 Tus descargas: {descargas}
🎉 ¡Descargas ILIMITADAS y GRATIS!""")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    registrar_usuario(user_id)

    # Detectar y procesar enlaces de canales
    if "t.me/c/" in text:
        # Detectar canal de origen
        canal_id, tipo_contenido = detectar_canal_origen(text)
        
        if canal_id is None:
            await update.message.reply_text(
                "❌ **Canal no reconocido**\n\n"
                "🎬 Canales válidos:\n"
                "• Canal de PELÍCULAS\n"
                "• Canal de SERIES\n\n"
                "💡 Asegúrate de enviar enlaces de estos canales."
            )
            return
        
        message_ids = await detectar_enlaces_serie(text)
        
        if len(message_ids) > 1:
            await manejar_serie_enlaces(update, context, message_ids, canal_id, tipo_contenido)
            return
        
        elif len(message_ids) == 1:
            message_id = message_ids[0]
            descargas = obtener_descargas_usuario(user_id)
            processing_msg = await update.message.reply_text(f"⚡ Procesando tu solicitud... (Descarga #{descargas + 1})")
            
            try:
                await processing_msg.edit_text(f"🔄 Verificando mensaje en el canal...")
                
                try:
                    message_info = await context.bot.get_chat(canal_id)
                    logger.info(f"Canal encontrado: {message_info.title if hasattr(message_info, 'title') else 'Sin título'}")
                except Exception as chat_error:
                    logger.error(f"Error accediendo al canal: {chat_error}")
                    await processing_msg.edit_text("❌ No puedo acceder al canal. Verifica que el bot sea administrador del canal con todos los permisos necesarios.")
                    return
                
                await processing_msg.edit_text(f"🔄 Copiando video del canal...")
                
                try:
                    copied_msg = await context.bot.copy_message(
                        chat_id=update.effective_chat.id,
                        from_chat_id=canal_id,
                        message_id=message_id
                    )
                    logger.info(f"Mensaje copiado exitosamente: new_msg_id={copied_msg.message_id}")
                    contar_descarga_usuario(user_id)
                    await processing_msg.delete()
                    return
                    
                except Exception as copy_error:
                    copy_error_msg = str(copy_error).lower()
                    logger.warning(f"Copy falló: {copy_error}")
                    
                    if "message to copy not found" in copy_error_msg or "not found" in copy_error_msg:
                        await processing_msg.edit_text(f"❌ Mensaje #{message_id} no encontrado en el canal.\n\n💡 **Pasos para solucionarlo:**\n1. Ve al canal y envía un video NUEVO\n2. Haz clic derecho en el mensaje → 'Copiar enlace del mensaje'\n3. Envía ese enlace fresco al bot")
                        return
                    elif "forbidden" in copy_error_msg or "chat not found" in copy_error_msg:
                        await processing_msg.edit_text("❌ **Error de permisos del bot**\n\n🔧 **Solución:**\n1. Ve a tu canal privado\n2. Añade este bot como administrador\n3. Dale estos permisos:\n   • Leer mensajes\n   • Enviar mensajes\n   • Gestionar mensajes\n4. Intenta de nuevo")
                        return
                
                await processing_msg.edit_text(f"🔄 Intentando reenvío alternativo...")
                try:
                    forwarded_msg = await context.bot.forward_message(
                        chat_id=update.effective_chat.id,
                        from_chat_id=canal_id,
                        message_id=message_id
                    )
                    logger.info(f"Mensaje forwardeado exitosamente: new_msg_id={forwarded_msg.message_id}")
                    contar_descarga_usuario(user_id)
                    await processing_msg.edit_text("✅ Video reenviado del canal (método alternativo).")
                    
                except Exception as forward_error:
                    forward_error_msg = str(forward_error).lower()
                    logger.error(f"Forward también falló: {forward_error}")
                    
                    if "message to forward not found" in forward_error_msg or "not found" in forward_error_msg:
                        await processing_msg.edit_text(f"❌ **Mensaje #{message_id} no existe**\n\n🔍 **Qué verificar:**\n1. ¿El mensaje fue eliminado del canal?\n2. ¿El enlace es de otro canal diferente?\n3. ¿El número del mensaje es correcto?\n\n💡 Envía un video nuevo al canal y usa su enlace.")
                    elif "forbidden" in forward_error_msg or "chat not found" in forward_error_msg:
                        await processing_msg.edit_text(f"❌ **Bot sin acceso al canal**\n\nCanal ID: `{canal_id}`\nMensaje ID: `{message_id}`\n\n🔧 **Solución:**\n1. Añade el bot como admin del canal\n2. Dale permisos completos\n3. Verifica que el CANAL_ID sea correcto")
                    else:
                        await processing_msg.edit_text(f"❌ **Error técnico**\n```\n{str(forward_error)[:200]}...\n```\n\n🔄 Intenta con un mensaje más reciente del canal.")
                        
            except Exception as e:
                logger.error(f"Error procesando enlace individual: {e}")
                await processing_msg.edit_text("❌ Error procesando el enlace.")
            return
    
    # Si no es un enlace válido del canal
    await update.message.reply_text(
        "❌ **Enlace no reconocido**\n\n"
        "✅ **Formato válido:**\n"
        "• Enlace del canal: `t.me/c/.../123`\n"
        "• **SERIE COMPLETA:** Envía varios enlaces del canal juntos en un solo mensaje\n\n"
        "📺 **Ejemplo para series:**\n"
        "Pega múltiples enlaces (uno por línea) para enviar una serie completa"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_usuarios = contar_usuarios()
    total_descargas = sum(descargas_usuarios.values())
    
    await update.message.reply_text(
        f"📊 **Estadísticas del bot:**\n"
        f"👥 Usuarios registrados: {total_usuarios}\n"
        f"📥 Total descargas: {total_descargas}\n"
        f"🎬 Canal películas: {CANAL_PELICULAS_ID}\n"
        f"📺 Canal series: {CANAL_SERIES_ID}\n"
        f"🎉 Sin límites de descarga"
    )

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando temporal para obtener el ID de un chat"""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    title = getattr(update.effective_chat, 'title', 'Sin título')
    
    await update.message.reply_text(
        f"ℹ️ **Información del chat actual:**\n"
        f"🆔 **ID:** `{chat_id}`\n"
        f"📱 **Tipo:** {chat_type}\n"
        f"📝 **Título:** {title}"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Uso: /broadcast <tu mensaje aquí>")
        return
    
    mensaje = " ".join(context.args)
    await update.message.reply_text("✅ Iniciando envío masivo...")

    enviados = 0
    errores = 0
    
    for user_id_str, user_data in usuarios.items():
        try:
            await context.bot.send_message(
                chat_id=int(user_id_str), 
                text=f"🚨 **Mensaje del administrador:**\n\n{mensaje}", 
                parse_mode='Markdown'
            )
            enviados += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            errores += 1
            logger.error(f"Error enviando a {user_id_str}: {e}")
    
    await update.message.reply_text(f"📤 Envío completado:\n✅ Enviados: {enviados}\n❌ Errores: {errores}")

# --- ENDPOINTS DEL SERVIDOR ---

async def health_check(request):
    return web.json_response({
        "status": "ok", 
        "bot_active": True,
        "users": contar_usuarios(),
        "total_downloads": sum(descargas_usuarios.values()),
        "canales": {
            "peliculas": CANAL_PELICULAS_ID,
            "series": CANAL_SERIES_ID
        }
    })

async def telegram_webhook(request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot)
        asyncio.create_task(application.process_update(update))
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return web.Response(status=500)

async def root_handler(request):
    return web.Response(
        text="🤖 Bot de Películas y Series - Descargas ilimitadas ✅",
        content_type="text/plain"
    )

# --- INICIALIZACIÓN ---

async def init_app():
    global application, bot
    
    logger.info("Inicializando bot...")
    logger.info(f"🎬 Canal PELÍCULAS (privado): ID={CANAL_PELICULAS_ID}")
    logger.info(f"📺 Canal SERIES (privado): ID={CANAL_SERIES_ID}")
    logger.info("🎉 Modo: DESCARGAS ILIMITADAS (sin canales obligatorios)")
    logger.info("✅ Videos SE PUEDEN compartir")
    
    application = Application.builder().token(BOT_TOKEN).build()
    bot = application.bot

    # Registrar handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("getchatid", get_chat_id))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.initialize()
    await application.start()
    webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook configurado: {webhook_url}")

    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)
    app.router.add_get("/health", health_check)
    app.router.add_get("/", root_handler)
    
    # Iniciar tareas en segundo plano
    asyncio.create_task(keep_alive())
    
    logger.info("✅ Bot inicializado correctamente con:")
    logger.info("   • 2 canales de contenido (Películas y Series)")
    logger.info("   • Descargas ilimitadas sin restricciones")
    logger.info("   • Sin verificación de canales obligatorios")
    return app

async def main():
    try:
        app = await init_app()
        return app
    except Exception as e:
        logger.error(f"Error inicializando: {e}")
        raise

if __name__ == "__main__":
    try:
        web.run_app(main(), port=PORT, host="0.0.0.0")
    except Exception as e:
        logger.error(f"Error ejecutando servidor: {e}") 
