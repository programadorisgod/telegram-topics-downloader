"""
Exporta todos los topics y mensajes de un grupo/foro de Telegram a JSON,
listo para usar como insumo de un knowledge graph.

Requisitos:
    pip install telethon

Antes de correr:
    1. Ve a https://my.telegram.org -> API development tools
    2. Exporta las variables de entorno: KNW_API_ID y KNW_API_HASH
    3. La primera vez te pedirá tu número y un código que llega por Telegram

Uso:
    export KNW_API_ID=12345
    export KNW_API_HASH=abcd
    export KNW_GROUP_IDENTIFIER="https://t.me/+XXXX"
    python main.py
"""

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

from telethon import TelegramClient, events, utils
from telethon.tl.types import Channel

try:
    # Telethon reciente: vive en messages, con el parámetro "peer"
    from telethon.tl.functions.messages import GetForumTopicsRequest
    _PARAM_NAME = "peer"
except ImportError:
    # Telethon viejo: vive en channels, con el parámetro "channel"
    from telethon.tl.functions.channels import GetForumTopicsRequest
    _PARAM_NAME = "channel"

def load_env_file(path=".env"):
    """Carga .env sin dependencias. Las vars ya exportadas ganan (si no están vacías)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            if s.startswith("export "):
                s = s[len("export "):].lstrip()
            key, _, rest = s.partition("=")
            key = key.strip()
            rest = rest.strip()
            if rest[:1] in ('"', "'"):
                # valor entre comillas; el comentario va DESPUÉS del par de cierre
                end = rest.find(rest[0], 1)
                val = rest[1:end] if end != -1 else rest
            else:
                val = rest.split(" #", 1)[0].strip()  # comentario inline fuera de comillas
            if key and val and not os.environ.get(key):
                os.environ[key] = val


load_env_file()

# ---------- CONFIG (desde environment) ----------
API_ID = int(os.getenv("KNW_API_ID", "0") or 0)       # obligatorio: tu api_id (número)
API_HASH = os.getenv("KNW_API_HASH", "")              # obligatorio: tu api_hash
SESSION_NAME = os.getenv("KNW_SESSION_NAME", "mi_sesion")   # archivo .session local, reutilizable
GROUP_IDENTIFIER = os.getenv("KNW_GROUP_IDENTIFIER", "")    # username, link, o ID numérico del grupo
TOPICS_DIR = os.getenv("KNW_TOPICS_DIR", "topics")    # cada topic tendrá su propia carpeta aquí dentro
DOWNLOAD_MEDIA = os.getenv("KNW_DOWNLOAD_MEDIA", "true").lower() in ("1", "true", "yes")  # False = solo JSON
MEDIA_DOWNLOAD_RETRIES = int(os.getenv("KNW_MEDIA_DOWNLOAD_RETRIES", "4"))  # reintentos ante timeouts


def validate_config():
    if not API_ID or not API_HASH or not GROUP_IDENTIFIER:
        raise SystemExit(
            "Faltan variables de entorno: KNW_API_ID, KNW_API_HASH y KNW_GROUP_IDENTIFIER son obligatorias.\n"
            "Ver README.md para el setup."
        )
# ------------------------------------------------


def safe_filename(name, fallback):
    """Convierte el título de un topic en un nombre de archivo/carpeta válido."""
    name = (name or fallback).strip()
    keep = "-_. "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned[:80] or fallback


def extract_topic_id(msg):
    """Devuelve el id del topic del mensaje (0 = topic General). None si no hay reply.

    Con `is not None` (no `or`) para que General (reply_to_top_id == 0) no se
    confunda con un reply a un mensaje suelto.
    """
    if msg.reply_to and msg.reply_to.reply_to_top_id is not None:
        return msg.reply_to.reply_to_top_id
    if msg.reply_to and msg.reply_to.reply_to_msg_id:
        return msg.reply_to.reply_to_msg_id
    return None


def build_client():
    return TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
        connection_retries=10,   # reintentos de conexión ante caídas
        retry_delay=2,           # segundos entre reintentos
        timeout=30,              # segundos de espera por request antes de timeout
        request_retries=5,       # reintentos por request individual (incluye GetFileRequest)
    )


async def serialize_message(client, msg, topic_dir):
    local_path = None

    if DOWNLOAD_MEDIA and msg.media:
        ext = utils.get_extension(msg.media) or ""
        target = os.path.join(topic_dir, f"{msg.id}{ext}")

        for attempt in range(1, MEDIA_DOWNLOAD_RETRIES + 1):
            try:
                local_path = await client.download_media(msg, file=target)
                break
            except Exception as e:
                wait = 2 ** attempt  # backoff: 2s, 4s, 8s, 16s...
                if attempt == MEDIA_DOWNLOAD_RETRIES:
                    print(f"     [!] Falló definitivamente la descarga del msg {msg.id}: {e}")
                else:
                    print(f"     [!] Timeout/error bajando msg {msg.id} (intento {attempt}/{MEDIA_DOWNLOAD_RETRIES}), "
                          f"reintentando en {wait}s...")
                    await asyncio.sleep(wait)

    return {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "sender_id": msg.sender_id,
        "text": msg.message,
        # Si el mensaje es una imagen/video/doc con pie de foto, Telegram lo manda
        # como msg.message -> queda duplicado aquí explícitamente para que no
        # se te pierda al procesar solo mensajes con media.
        "caption": msg.message if msg.media and msg.message else None,
        "reply_to_msg_id": msg.reply_to.reply_to_msg_id if msg.reply_to else None,
        "topic_id": extract_topic_id(msg),
        "is_reply": bool(msg.reply_to),
        "media_type": type(msg.media).__name__ if msg.media else None,
        "local_media_path": local_path,
    }


async def get_all_topics(client, entity):
    """Trae todos los topics del foro (paginando)."""
    topics = []
    offset_date = 0
    offset_id = 0
    offset_topic = 0

    while True:
        kwargs = {
            _PARAM_NAME: entity,
            "offset_date": offset_date,
            "offset_id": offset_id,
            "offset_topic": offset_topic,
            "limit": 100,
        }
        result = await client(GetForumTopicsRequest(**kwargs))
        if not result.topics:
            break

        topics.extend(result.topics)

        last = result.topics[-1]
        offset_topic = last.id
        offset_id = last.top_message
        # offset_date se puede sacar del último mensaje si se necesita, dejamos 0 para simplicidad
        if len(result.topics) < 100:
            break

    return topics


async def main():
    client = build_client()
    await client.start()

    entity = await client.get_entity(GROUP_IDENTIFIER)

    if not isinstance(entity, Channel) or not getattr(entity, "forum", False):
        print("Este chat no es un supergrupo con topics (foro) habilitado.")
        await client.disconnect()
        return

    print(f"Conectado a: {entity.title}")

    topics = await get_all_topics(client, entity)
    print(f"Encontrados {len(topics)} topics")

    os.makedirs(TOPICS_DIR, exist_ok=True)
    index = []  # resumen liviano de todos los topics, para navegar rápido

    for topic in topics:
        print(f"  -> Bajando topic: {topic.title} (id={topic.id})")
        messages = []

        # Una carpeta por topic con TODO adentro: su JSON y su media juntos
        topic_folder_name = f"{topic.id}_{safe_filename(topic.title, f'topic_{topic.id}')}"
        topic_path = os.path.join(TOPICS_DIR, topic_folder_name)
        media_dir = os.path.join(topic_path, "media")
        os.makedirs(topic_path, exist_ok=True)
        if DOWNLOAD_MEDIA:
            os.makedirs(media_dir, exist_ok=True)

        # iter_messages con reply_to trae todos los mensajes del hilo del topic
        async for msg in client.iter_messages(entity, reply_to=topic.id, limit=None):
            messages.append(await serialize_message(client, msg, media_dir))

        topic_export = {
            "group": entity.title,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "topic_id": topic.id,
            "topic_title": topic.title,
            "message_count": len(messages),
            "messages": messages,
        }

        filepath = os.path.join(topic_path, "data.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(topic_export, f, ensure_ascii=False, indent=2)

        index.append({
            "id": topic.id,
            "title": topic.title,
            "message_count": len(messages),
            "folder": topic_folder_name,
        })
        print(f"     {len(messages)} mensajes -> {topic_path}/")

    with open(os.path.join(TOPICS_DIR, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"group": entity.title, "topics": index}, f, ensure_ascii=False, indent=2)

    print(f"\nExportación completa -> carpeta '{TOPICS_DIR}/' ({len(topics)} topics + _index.json)")
    await client.disconnect()


_topic_titles_cache = {}  # topic_id -> título, para no repetir get_messages por mensaje

# hook opcional para el modo listen: si algo lo setea (p.ej. la API) se llama
# después de cada mensaje nuevo, para reindexar la búsqueda en vivo.
# Firma: async def hook(record: dict) -> None
ON_NEW_MESSAGE = None


async def get_topic_title(client, entity, topic_id):
    """Título del topic desde su mensaje raíz (con cache)."""
    if topic_id in _topic_titles_cache:
        return _topic_titles_cache[topic_id]
    try:
        root = await client.get_messages(entity, ids=topic_id)
        title = None
        if root and root.action and hasattr(root.action, "title"):
            title = root.action.title
    except Exception:
        title = None
    title = title or f"topic_{topic_id}"
    _topic_titles_cache[topic_id] = title
    return title


def _load_topic_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def listen_main():
    """Escucha en tiempo real y hace append de cada mensaje nuevo a messages.jsonl."""
    client = build_client()
    await client.start()

    entity = await client.get_entity(GROUP_IDENTIFIER)
    if not isinstance(entity, Channel) or not getattr(entity, "forum", False):
        print("Este chat no es un supergrupo con topics (foro) habilitado.")
        await client.disconnect()
        return

    os.makedirs(TOPICS_DIR, exist_ok=True)
    print(f"Escuchando en tiempo real: {entity.title}")
    print("Ctrl+C para detener (o matá el proceso en tmux/systemd).\n")

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        msg = event.message
        topic_id = extract_topic_id(msg)
        if topic_id is None:  # mensaje suelto en General (sin topic)
            topic_id, title = 0, "General"
        else:
            title = await get_topic_title(client, entity, topic_id)

        folder = f"{topic_id}_{safe_filename(title, f'topic_{topic_id}')}"
        topic_path = os.path.join(TOPICS_DIR, folder)
        os.makedirs(topic_path, exist_ok=True)

        media_dir = os.path.join(topic_path, "media")
        if DOWNLOAD_MEDIA and msg.media:
            os.makedirs(media_dir, exist_ok=True)

        record = await serialize_message(client, msg, media_dir)
        record["received_at"] = datetime.now(timezone.utc).isoformat()

        data_path = os.path.join(topic_path, "data.json")
        export = _load_topic_file(data_path) or {
            "group": entity.title,
            "exported_at": record["received_at"],
            "topic_id": topic_id,
            "topic_title": title,
            "message_count": 0,
            "messages": [],
        }
        if any(m["id"] == record["id"] for m in export["messages"]):
            return  # ya estaba (ej. coincidió con un re-export)
        export["messages"].append(record)
        export["message_count"] = len(export["messages"])
        export["exported_at"] = record["received_at"]

        # escritura atómica para no dejar el archivo a medias
        # ponytail: si el export masivo corre a la vez, el último en escribir gana (re-export después aplana)
        tmp = f"{data_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        os.replace(tmp, data_path)

        print(f"[NUEVO] topic='{title}' msg_id={msg.id} media={record['media_type']} -> {folder}")

        if ON_NEW_MESSAGE:
            try:
                await ON_NEW_MESSAGE(record)
            except Exception as e:
                print(f"[listen] hook falló: {e}")

    await client.run_until_disconnected()


def run():
    parser = argparse.ArgumentParser(description="Exporta topics de un foro de Telegram a JSON.")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="en vez del export masivo, quedate escuchando mensajes nuevos en tiempo real",
    )
    args = parser.parse_args()
    validate_config()
    asyncio.run(listen_main() if args.listen else main())


if __name__ == "__main__":
    run()
