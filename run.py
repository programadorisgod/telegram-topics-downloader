"""Entrypoint de la API. Se puede correr desde cualquier cwd:

    uv run python run.py
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
os.chdir(_ROOT)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("KNW_API_PORT", "8000")),
        reload=os.getenv("KNW_API_RELOAD", "false").lower() in ("1", "true", "yes"),
    )
