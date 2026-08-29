"""Entrypoint orquestador de knw (para docker / arranque de cero).

Flujo:
1. Si la carpeta de topics está vacía o no existe -> modo inicial: importa TODO
   de Telegram (baja cada topic y su data.json).
2. Terminó -> arranca la API. A partir de ahí, el startup de la app hace su
   auto-sync incremental y luego pasa a escucha en vivo (ver app/main.py).

    uv run python boot.py
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
os.chdir(_ROOT)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def topics_dir() -> Path:
    return Path(os.getenv("KNW_TOPICS_DIR", str(_ROOT / "topics")))


def needs_initial_import() -> bool:
    """True si la carpeta de topics está vacía o no existe."""
    d = topics_dir()
    if not d.exists():
        return True
    return not any(d.iterdir())


def initial_import() -> None:
    """Modo inicial: importa todo. Desconecta el cliente del auth para
    liberar la sesión SQLite, importa, y reconecta."""
    import asyncio
    from plugins.auth import auth
    from plugins.ingest import _sync_once

    if not auth.is_authorized():
        print("[boot] sin sesión, no puedo importar")
        return

    print("[boot] topics vacío -> modo inicial de importación completa")
    auth.disconnect()  # liberar el lock de la sesión SQLite
    try:
        added = asyncio.run(_sync_once())
        print(f"[boot] importación inicial terminada: {added} mensajes nuevos")
    finally:
        auth.reconnect()  # reconectar para que el listen funcione
    from plugins import registry
    registry.build_all()
    print("[boot] índice FTS5 reconstruido")


def session_ready() -> bool:
    """Hay sesión de Telegram autenticada que permita sincronizar."""
    from plugins.auth import auth
    return auth.is_authorized()


def main():
    if session_ready():
        if needs_initial_import():
            initial_import()
        else:
            print("[boot] topics presentes, salteo importación inicial")
    else:
        print("[boot] SIN sesión de Telegram: no importo y el sync/listen quedan "
              "en espera. Autenticá desde la UI (POST /api/auth/start o el modal en /).")

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("KNW_API_HOST", "0.0.0.0"),
        port=int(os.getenv("KNW_API_PORT", "8000")),
        reload=os.getenv("KNW_API_RELOAD", "false").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
