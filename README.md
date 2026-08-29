# knw

Buscador + IA sobre recursos de desarrollo guardados como topics de un foro de
Telegram. Todo vive detrás de un **sistema de plugins**, empezando por la ingesta.
La IA es agnóstica al modelo (hoy DeepSeek, intercambiable sin tocar la app).

## Arquitectura

```
knw/
├── boot.py                  # orquestador: importa si topics vacío, luego arranca la API
├── run.py                   # solo API (auto-sync + listen en el startup)
├── main.py                  # export masivo + --listen (ingesta manual)
├── app/main.py              # FastAPI: monta routers + startup (sync -> listen en vivo)
├── plugins/                 # registro de plugins (el core del sistema)
│   ├── base.py              # contrato Plugin: name, router(), build()
│   ├── auth/                # login interactivo Telegram (phone → code → 2FA)
│   ├── search/              # indexa topics en SQLite FTS5 + busca (BM25 + sinónimos)
│   ├── ai/                  # orquesta search + ChatProvider (con caché TTL)
│   └── ingest/              # sync incremental de Telegram a disco (con API + auto)
├── providers/               # proveedores de chat, aislados de la app
│   ├── base.py              # contrato ChatProvider + registry + get_provider(env)
│   └── deepseek.py          # impl actual (OpenAI-compatible)
├── ui/                      # React + Vite + Tailwind (pnpm)
├── Dockerfile               # multi-stage: build UI + app python
└── docker-compose.yml       # un container, volumen de datos en /data
```

La app **no conoce** ningún plugin: los pide al registry por nombre y monta sus
routers. Idéntico para la IA: `providers/base.py` resuelve el proveedor por env,
la orquestación nunca importa "deepseek".

## Setup (una vez)

```bash
uv sync            # deps Python (FastAPI, uvicorn, httpx, telethon)
cd ui && pnpm install && cd ..   # deps UI
```

Credenciales en `.env` (Ver `README` original para las de Telegram):

```
KNW_API_ID=...
KNW_API_HASH=...
KNW_GROUP_IDENTIFIER=...
# IA (solo para que responda /api/ask):
KNW_DEEPSEEK_API_KEY=sk-...
# opcional
KNW_AI_PROVIDER=deepseek      # default deepseek
KNW_AUTO_SYNC=true            # default: sync Telegram en background al arrancar
KNW_TOPICS_DIR=topics
KNW_DB_PATH=knw.db
```

## Levantar

```bash
# terminal 1 — API (búsqueda + IA + sync automático). Funciona desde cualquier cwd.
uv run python run.py             # en :8000 (KNW_API_PORT para cambiar puerto)

# terminal 2 — UI (dev, proxya /api a :8000)
cd ui && pnpm dev                # en :5173
```

### Orquestador: `boot.py` (recomendado)

`boot.py` maneja el arranque desde cero y, para producción/Docker, es el entrypoint:

```bash
uv run python boot.py
```

Flujo:
1. **Si `topics/` está vacío o no existe → modo inicial**: importa TODO de Telegram
   (baja cada topic y su `data.json`). Si ya hay topics, lo saltea.
2. **Arranca la API.** En su startup, la app:
   - indexa en FTS5 lo que ya hay en disco (ms),
   - corre un **sync incremental en background** (baja lo nuevo, reindexa, termina),
   - y al terminar el sync, **pasa a escucha en vivo** (`--listen`): queda como
     dueño de la sesión de Telegram y por cada mensaje nuevo hace append al
     `data.json` **y reindexa** la búsqueda. No se reinicia: vive mientras la API.

O sea: arranque → sync → (termina) → listen en vivo, todo en un solo proceso.
La sesión de Telegram la toca una sola cosa a la vez (listo el conflicto).

`run.py` sigue disponible si querés solo la API sin el orquestador:

```bash
uv run python run.py      # solo API (+ auto-sync y listen en el startup)
```

Las opciones manuales de ingesta siguen disponibles (para test/manual):

```bash
uv run main.py            # export masivo completo (una vez)
uv run main.py --listen   # escucha en tiempo real (solo si NO hay API prendida con la misma sesión)
```

> Nota: correr `main.py --listen` a la vez que la API usa la misma `mi_sesion.session`
> genera conflicto de sesión. Con `boot.py` no lo necesitás.

## Docker

Todo en un solo container: build de la UI + API, con `boot.py` como entrypoint
(importa si `topics/` está vacío, luego API + sync + listen en vivo).

```bash
docker compose up --build
# -> http://localhost:8000  (sirve la UI compilada y la API en el mismo puerto)
```

### Login interactivo

La primera vez que levantás Docker, **no hay sesión de Telegram**. El container
arranca la API y la UI muestra un **modal de login** con tres pasos:

1. **Número de teléfono** (con código de país, ej: `+5491155551234`)
2. **Código de verificación** (lo envía Telegram por SMS/quad)
3. **Contraseña 2FA** (opcional, solo si tenés autenticación en dos pasos habilitada)

Al completar el login, el container automáticamente:
- Descarga todos los topics de Telegram (puede demorar minutos la primera vez)
- Reconstruye el índice de búsqueda FTS5
- Pasa a escucha en vivo (captura mensajes nuevos)

El estado del sync se muestra como **banner** en la parte superior de la UI.

### Persistencia

- **Sesión de Telegram**: `/data/knw_session` (volumen `knw_data`)
- **Topics y datos**: `/data/topics/` y `/data/knw.db` (mismo volumen)

Si el container se reinicia con sesión existente, arranca directo sin pedir login.

## Endpoints

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/api/health` | estado + plugins cargados |
| `GET` | `/api/status` | estado de la app (`startup`, `importing`, `reindexing`, `listening`, `error`) |
| `GET` | `/api/auth/status` | `{authorized: bool}` — si hay sesión válida |
| `POST` | `/api/auth/start` | `{phone}` → envía código de verificación |
| `POST` | `/api/auth/complete` | `{code, password?}` → completa login, dispara import |
| `GET` | `/api/search?q=vibrar` | búsqueda FTS5 (sinónimos, wildcards, stopwords) |
| `POST` | `/api/ask` `{query}` | busca + IA curada (caché 5 min) |
| `POST` | `/api/ingest/sync` | sync incremental manual |
| `POST` | `/api/search/rebuild` | reindexa forzado |

## Tests / self-checks (sin frameworks)

```bash
uv run python -m plugins.search.index_demo   # index + búsqueda FTS5
uv run python -m plugins.ai.ai_demo          # orquestación AI con un provider fake (sin tocar DeepSeek)
```

## Aggregar un plugin

1. Creá `plugins/<nombre>/__init__.py` que defina `class X(Plugin)` con `name`,
   `router()` (un `fastapi.APIRouter`) y opcional `build()`.
2. Al final del archivo: `plugin = X()`. El registry lo detecta solo.
3. Agregar un proveedor de IA: clase en `providers/` que herede `ChatProvider`,
   decorada con `@register`, `name` único. Se elige por `KNW_AI_PROVIDER`.

## Notas

- Si `KNW_DEEPSEEK_API_KEY` no está configurada, `/api/ask` responde con
  `ia_activa: false` y los resultados de la búsqueda directa. La UI muestra un
  badge "IA desactivada" avisando que los resultados pueden no ser 100% exactos.
- Búsqueda: FTS5 en SQLite + ranking BM25. Sinónimos es→en (ej: "vibrar" → "vibrate"),
  wildcards automáticos y stopwords removidos. Con ~2.5k mensajes indexa en ms.
  Los hits priorizan mensajes con links/recursos para que la IA tenga contexto.
- Caché de IA: en memoria, TTL 5 min, reset simple al llenarse (ponytail).
- `topics/`, `.env`, `*.session` y `knw.db` están gitignored.
