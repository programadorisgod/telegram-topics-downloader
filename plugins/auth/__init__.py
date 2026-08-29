"""Plugin auth: login de Telegram por pasos (cuenta personal), sin crashear.

El cliente de Telethon vive en un thread con su propio event loop, así puede
quedarse conectado entre requests de la UI: POST /start manda el código, POST
/complete ingresa el código (y password 2FA si lo pide). Al completar guarda
la sesión en el archivo que ya usa main.py (KNW_SESSION_NAME).

Endpoints:
    GET  /api/auth/status      -> {authorized: bool}
    POST /api/auth/start       -> {phone}      -> {sent: True, ...}
    POST /api/auth/complete    -> {code, password?} -> {ok} | {need_password: True}
"""

import asyncio
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from plugins.base import Plugin


class TelegramAuth:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._client = None
        self._phone = None
        self._phone_code_hash = None
        self._lock = threading.Lock()

    # --- plumbing del event loop en su thread ---
    def _ensure(self):
        if self._loop is not None:
            return
        with self._lock:
            if self._loop is not None:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run, daemon=True, name="knw-telegram")
            self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout: float = 60.0):
        self._ensure()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except Exception as e:
            return {"error": str(e)}

    # --- corutinas (se ejecutan en el loop del thread) ---
    async def _a_client(self):
        if self._client is None:
            import main as exporter
            self._client = exporter.build_client()
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    # --- API pública (síncrona, bloquea hasta resolver) ---
    def is_authorized(self) -> bool:
        async def go():
            try:
                c = await self._a_client()
                return await c.is_user_authorized()
            except Exception:
                return False
        res = self._call(go())
        if isinstance(res, dict):
            return False
        return bool(res)

    def disconnect(self) -> None:
        """Desconecta el cliente de Telegram para liberar la sesión SQLite."""
        async def go():
            if self._client and self._client.is_connected():
                await self._client.disconnect()
        try:
            self._call(go(), timeout=5.0)
        except Exception:
            pass

    def reconnect(self) -> None:
        """Reconecta el cliente de Telegram (libera el lock de SQLite)."""
        async def go():
            if self._client and not self._client.is_connected():
                await self._client.connect()
        try:
            self._call(go(), timeout=10.0)
        except Exception:
            pass

    def request_code(self, phone: str) -> None:
        async def go():
            c = await self._a_client()
            res = await c.send_code_request(phone)
            self._phone = phone
            self._phone_code_hash = res.phone_code_hash
        self._call(go())

    def complete(self, code: str, password: str | None = None) -> dict:
        from telethon.errors import (
            SessionPasswordNeededError,
            PhoneCodeInvalidError,
            PhoneCodeExpiredError,
        )

        async def go():
            c = await self._a_client()
            try:
                await c.sign_in(phone=self._phone, code=code,
                                phone_code_hash=self._phone_code_hash)
                return {"ok": True}
            except SessionPasswordNeededError:
                if not password:
                    return {"need_password": True}
                await c.sign_in(password=password)
                return {"ok": True}
            except PhoneCodeInvalidError:
                return {"error": "code_invalid"}
            except PhoneCodeExpiredError:
                return {"error": "code_expired"}
            except Exception as e:
                return {"error": str(e)}

        return self._call(go())


auth = TelegramAuth()


class _Start(BaseModel):
    phone: str


class _Complete(BaseModel):
    code: str
    password: str | None = None


class AuthPlugin(Plugin):
    name = "auth"

    def build(self):
        # NO se arranca el client hasta que haga falta (status/login).
        pass

    def router(self):
        r = APIRouter(prefix="/api/auth", tags=["auth"])

        @r.get("/status")
        def status():
            return {"authorized": auth.is_authorized()}

        @r.post("/start")
        def start(body: _Start):
            auth.request_code(body.phone.strip())
            return {"sent": True}

        @r.post("/complete")
        def complete(body: _Complete):
            res = auth.complete(body.code.strip(), body.password)
            if isinstance(res, dict) and res.get("ok"):
                def _go():
                    from app.main import _auto_sync
                    _auto_sync(force=True)
                threading.Thread(target=_go, daemon=True).start()
            elif isinstance(res, dict) and res.get("error"):
                print(f"[auth] login falló: {res['error']}", flush=True)
            return res

        return r


plugin = AuthPlugin()
