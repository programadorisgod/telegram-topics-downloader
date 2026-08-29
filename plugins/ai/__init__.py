"""Plugin ai: convierte una query en lenguaje natural a una respuesta curada.

Flujo: query -> busca en el índice FTS5 (plugin search) -> arma contexto con
los fragments que matchean -> ChatProvider devuelve la respuesta con links.
"""

import time

from fastapi import APIRouter

from plugins.base import Plugin
from plugins.search.index import SearchIndex
from providers.base import get_provider

_TOP_TOPICS = 8
_HITS_PER_TOPIC = 16


class AiPlugin(Plugin):
    name = "ai"

    def __init__(self, search: SearchIndex | None = None):
        self.search = search
        self._cache: dict[str, tuple[float, str]] = {}
        self._cache_ttl = 300  # 5 min
        self._max_cache = 200

    def build(self):
        if self.search is None:
            from plugins import registry
            self.search = registry.get("search").index

    def _cached(self, key: str) -> str | None:
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self._cache_ttl:
            return hit[1]
        return None

    def _cache_set(self, key: str, value: str):
        if len(self._cache) >= self._max_cache:
            self._cache.clear()  # ponytail: reset total, LRU si importa
        self._cache[key] = (time.time(), value)

    def _build_context(self, query: str) -> tuple[list, str]:
        topics = self.search.search(query, limit=_TOP_TOPICS, max_per_topic=_HITS_PER_TOPIC)
        if not topics:
            return topics, ""
        lines = []
        for t in topics:
            lines.append(f"\n### {t['topic_title']} (carpeta: {t['folder']})")
            for h in t["hits"]:
                text = h["text"].replace("\n", " ")
                base = f"- {text}"
                if h.get("links"):
                    base += " [RECURSO/LINKS: " + ", ".join(h["links"]) + "]"
                lines.append(base)
        return topics, "\n".join(lines)

    def ask(self, query: str, provider=None) -> dict:
        key = query.strip().lower()
        cached = self._cached(key)
        topics, context = self._build_context(query)

        system = (
            "Sos un asistente que apunta a recursos de programación e ingeniería de "
            "sistemas/software. Debajo te paso los RESULTADOS de una búsqueda real sobre "
            "una base de topics: son la mejor evidencia que tenés.\n\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. Respondé EXCLUSIVAMENTE usando esos resultados. No uses tu conocimiento "
            "general: no inventes recursos, herramientas ni links que no estén en el contexto.\n"
            "2. Si un resultado trae [RECURSO/LINKS: <url>], mostrá esas URLs textualmente "
            "como recursos concretos y con el título del topic al que pertenecen.\n"
            "3. Estructura la respuesta así: primero los recursos que SÍ encontraste "
            "(con su link y topic), y solo si no hay nada relacionado aclaralo en una línea.\n"
            "4. Si no hay resultados (`(sin resultados)`), decilo en una línea y NO inventes "
            "herramientas externas.\n"
            "5. Si la pregunta tiene erratas o typos (ej. 'seguirp'), interpretá la intención "
            "más probable y respondé igual; no te detengas en el error.\n"
            "6. Respondé en el idioma de la pregunta. Cada topic vive en la carpeta indicada."
        )

        if cached:
            text = cached
        else:
            user = f"Pregunta: {query}\n\nResultados de la búsqueda sobre la base de topics:\n{context or '(sin resultados)'}"
            p = provider or get_provider()
            text = p.chat(system, [{"role": "user", "content": user}])
            self._cache_set(key, text)

        return {
            "query": query,
            "cached": cached is not None,
            "topics": topics,
            "answer": text,
        }

    def router(self):
        from fastapi import APIRouter
        from providers.base import ProviderConfigError
        r = APIRouter(prefix="/api/ask", tags=["ai"])

        @r.post("")
        def ask(payload: dict):
            q = (payload.get("query") or "").strip()
            if not q:
                return {"error": "query requerida"}
            try:
                return self.ask(q)
            except ProviderConfigError as e:
                # falta la API key: la IA no está activa, pero la búsqueda sí funcionó
                topics, _ = self._build_context(q)
                return {"query": q, "ia_activa": False, "error": str(e), "topics": topics}

        return r


plugin = AiPlugin()
