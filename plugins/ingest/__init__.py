"""Plugin ingest: sincroniza los topics de Telegram a disco (incremental one-shot).

Reutiliza las funciones de main.py (Telethon) para hacer un sync que trae solo
lo nuevo y hace append a cada data.json, sin re-descargar todo. NO reemplaza
`uv run main.py --listen` (que queda para uso manual en segundo plano): este es
un modo on-demand que corre una vez y termina, invocable desde la API.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import main as exporter  # reutiliza build_client, serialize_message, etc.
from main import (
    DOWNLOAD_MEDIA,
    GROUP_IDENTIFIER,
    get_all_topics,
    safe_filename,
    serialize_message,
)
from telethon.tl.types import Channel

from plugins.base import Plugin

# raíz absoluta del proyecto: mismo path que usa el plugin search, independiente del cwd
_ROOT = Path(__file__).resolve().parent.parent.parent
TOPICS_DIR = str(Path(os.getenv("KNW_TOPICS_DIR", str(_ROOT / "topics"))))


def _load_topic_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def _sync_once() -> int:
    """Corre un sync incremental de todos los topics. Devuelve mensajes añadidos."""
    client = exporter.build_client()
    await client.start()
    entity = await client.get_entity(GROUP_IDENTIFIER)
    if not isinstance(entity, Channel) or not getattr(entity, "forum", False):
        print("[ingest] no es un foro, aborto sync")
        await client.disconnect()
        return 0

    os.makedirs(TOPICS_DIR, exist_ok=True)
    topics = await get_all_topics(client, entity)
    added = 0

    for topic in topics:
        folder = os.path.join(TOPICS_DIR, f"{topic.id}_{safe_filename(topic.title, f'topic_{topic.id}')}")
        os.makedirs(folder, exist_ok=True)
        media_dir = os.path.join(folder, "media")
        if DOWNLOAD_MEDIA:
            os.makedirs(media_dir, exist_ok=True)

        data_path = os.path.join(folder, "data.json")
        export = _load_topic_file(data_path) or {
            "group": entity.title,
            "topic_id": topic.id,
            "topic_title": topic.title,
            "message_count": 0,
            "messages": [],
        }
        existing = {m["id"] for m in export["messages"]}

        async for msg in client.iter_messages(entity, reply_to=topic.id, limit=None, reverse=True):
            if msg.id in existing:
                continue
            record = await serialize_message(client, msg, media_dir)
            record["received_at"] = datetime.now(timezone.utc).isoformat()
            export["messages"].append(record)
            existing.add(msg.id)
            added += 1

        if added > 0:
            export["message_count"] = len(export["messages"])
            export["exported_at"] = datetime.now(timezone.utc).isoformat()
            tmp = f"{data_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
            os.replace(tmp, data_path)

    await client.disconnect()
    return added


class IngestPlugin(Plugin):
    name = "ingest"

    def build(self):
        # sin acción: el sync se dispara explícitamente vía /api/ingest/sync
        pass

    def router(self):
        from fastapi import APIRouter
        r = APIRouter(prefix="/api/ingest", tags=["ingest"])

        @r.post("/sync")
        def sync():
            added = asyncio.run(_sync_once())
            return {"synced": True, "added": added}

        return r


plugin = IngestPlugin()


if __name__ == "__main__":
    print(f"Sync incremental: {asyncio.run(_sync_once())} mensajes nuevos")
