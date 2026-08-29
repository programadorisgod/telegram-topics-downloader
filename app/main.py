"""Punto de entrada FastAPI: monta los routers de cada plugin del registry.

La app no define endpoints propios de búsqueda/IA: se los pide a los plugins.
Al arrancar, si KNW_AUTO_SYNC está on (default), sincroniza Telegram a disco y
luego reindexa. Encendido:  uv run uvicorn app.main:app --reload
"""

import os
import sys
import threading
from pathlib import Path

# raíz del proyecto añadida a sys.path para poder arrancar desde cualquier cwd
# (p.ej. `uv run uvicorn app.main:app` también desde/ ui/)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from plugins import registry

app = FastAPI(title="knw", version="0.1.0")

# estado de la app: startup | idle | importing | reindexing | listening | error
_STATUS = {"state": "startup", "detail": ""}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ponytail: dev/CORS abierto; restringir en prod
    allow_methods=["*"],
    allow_headers=["*"],
)


def _live_reindex(record) -> None:
    """Reindexa tras cada mensaje nuevo del listen. Síncrono y barato (miles de msgs).
    ponytail: rebuild completo por mensaje; si el volumen crece, batch/debounce."""
    registry.get("search").index.build_if_stale(force=True)


async def _on_new_message(record) -> None:
    _live_reindex(record)


def _start_listen_live() -> None:
    """Pasa a escucha en tiempo real (bloquea el hilo para siempre)."""
    global _STATUS
    import asyncio
    import main as exporter
    from plugins.auth import auth

    auth.disconnect()
    exporter.ON_NEW_MESSAGE = _on_new_message
    _STATUS = {"state": "listening", "detail": "Escuchando mensajes nuevos"}
    print("[listen] escuchando mensajes nuevos en vivo", flush=True)
    asyncio.run(exporter.listen_main())


def _auto_sync(force: bool = False):
    """Sync incremental a Telegram; al terminar reindexa y pasa a escucha en vivo.

    force=True: saltar la verificación de sesión (útil post-login, cuando ya
    sabemos que la sesión es válida pero el check de Telegram podría fallar).
    """
    global _STATUS
    from plugins.ingest import _sync_once
    import asyncio
    from plugins.auth import auth
    print(f"[sync] _auto_sync iniciado (force={force})", flush=True)
    if not force and not auth.is_authorized():
        print("[sync] sin sesión de Telegram, sync/listen en espera. "
              "Autenticá desde la UI (POST /api/auth/start).", flush=True)
        _STATUS = {"state": "idle", "detail": "Sin sesión de Telegram"}
        return
    try:
        _STATUS = {"state": "importing", "detail": "Bajando topics de Telegram... puede demorar algunos minutos por ser la primera vez"}
        auth.disconnect()
        import time
        time.sleep(2)  # ponytail: dar tiempo a SQLite para liberar el lock
        try:
            added = asyncio.run(_sync_once())
            print(f"[sync] Telegram OK, {added} mensajes nuevos; reindexo...", flush=True)
        finally:
            auth.reconnect()
        _STATUS = {"state": "reindexing", "detail": f"Reindexando {added} mensajes nuevos..."}
        registry.get("search").index.build(force=True)
        print("[sync] reindexación terminada", flush=True)
    except Exception as e:
        print(f"[sync] falló (se usa data existente): {e}", flush=True)
        _STATUS = {"state": "error", "detail": str(e)}
    _start_listen_live()


@app.on_event("startup")
def _startup():
    # indexa lo que ya hay en disco (rápido) para servir de inmediato
    registry.build_all()
    auto_sync = os.getenv("KNW_AUTO_SYNC", "true").lower() in ("1", "true", "yes")
    if auto_sync:
        t = threading.Thread(target=_auto_sync, daemon=True)
        t.start()
        print("[startup] sync Telegram lanzado en background")


for name in registry.names():
    app.include_router(registry.get(name).router())
    print(f"[api] montado plugin: {name}")


@app.get("/api/health")
def health():
    return {"ok": True, "plugins": registry.names()}


@app.get("/api/status")
def status():
    return _STATUS


# Sirve la UI ya compilada (ui/dist) si existe: así el container es autocontenido.
# En dev sin dist, la app queda solo API y la UI corre aparte. Sin fallback SPA:
# la UI es de una página, html=True alcanza.
_from_root = Path(__file__).resolve().parent.parent
_dist = _from_root / "ui" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="ui")
    print(f"[api] sirviendo UI estática desde {_dist}")
