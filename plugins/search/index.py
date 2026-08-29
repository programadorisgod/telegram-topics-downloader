"""Índice FTS5 sobre los topics exportados y búsqueda.

El texto de ~3k mensajes es minúsculo: SQLite FTS5 indexa en ms y busca con
ranking BM25. Nada de Elasticsearch para un MVP. El índice vive en knw.db y
solo se regenera si cambió el _index.json de los topics.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

# raíz del proyecto = directorio padre de plugins/ (independiente del cwd)
_ROOT = Path(__file__).resolve().parent.parent.parent
TOPICS_DIR = Path(os.getenv("KNW_TOPICS_DIR", str(_ROOT / "topics")))
DB_PATH = Path(os.getenv("KNW_DB_PATH", str(_ROOT / "knw.db")))

# serializa build vs search dentro del proceso: el reindex (escritura) nunca
# pisa una lectura en curso. Entre procesos lo cubre el timeout de SQLite + WAL.
_db_lock = threading.Lock()


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    # timeout 30s: evita `database is locked` reutilizando la DB entre procesos
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.commit()
    return con


_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    topic_id, topic_title, msg_id, text, folder
);
"""


class SearchIndex:
    def __init__(self, db_path: Path = DB_PATH, topics_dir: Path = TOPICS_DIR):
        self.db_path = db_path
        self.topics_dir = topics_dir

    def _fingerprint(self) -> str:
        # ponytail: suma de mtime de los data.json detecta tanto el export masivo
        # (regenera _index.json) como el sync incremental (reescribe cada data.json)
        total = 0
        count = 0
        for d in sorted(self.topics_dir.glob("*/data.json")):
            try:
                st = d.stat()
                total += st.st_mtime_ns + st.st_size
                count += 1
            except OSError:
                continue
        return f"{count}:{total}"

    def build_if_stale(self, force: bool = False) -> int:
        """Reindexa si hace falta. Devuelve cantidad de mensajes indexados."""
        self.build(force=force)
        return self.count()

    def build(self, force: bool = False) -> None:
        with _db_lock:
            con = _connect(self.db_path)
            con.execute("PRAGMA secure_delete=ON")
            if force:
                con.execute("DROP TABLE IF EXISTS messages_fts")
            con.execute(_SCHEMA)
            con.execute("DELETE FROM messages_fts")
            con.commit()

            total = 0
            rows = []
            for data_path in sorted(self.topics_dir.glob("*/data.json")):
                try:
                    with open(data_path, encoding="utf-8") as f:
                        export = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                folder = data_path.parent.name
                for m in export.get("messages", []):
                    text = (m.get("text") or "").strip()
                    if not text:
                        continue
                    rows.append((export.get("topic_id"), export.get("topic_title"),
                                 m.get("id"), text, folder))
                    if len(rows) >= 500:
                        con.executemany(
                            "INSERT INTO messages_fts VALUES (?,?,?,?,?)", rows)
                        rows = []
            if rows:
                con.executemany("INSERT INTO messages_fts VALUES (?,?,?,?,?)", rows)
            con.commit()
            con.close()
            self.count()  # warm cache

    def count(self) -> int:
        con = _connect(self.db_path)
        con.execute(_SCHEMA)
        n = con.execute("SELECT count(*) FROM messages_fts").fetchone()
        con.close()
        return n[0]

    def search(self, q: str, limit: int = 20, max_per_topic: int = 3):
        """BM25 search, agrupando por topic.

        Query específica (3+ términos de señal): hits por BM25, priorizando los
        que traen links (recursos). Query genérica (<=2 términos, ej. "apis
        javascript"): muestra amplia del topic (recursos técnicos antes que
        ruido), para que la IA vea la riqueza del topic sin que el BM25 la
        entierre. Ver _signal_terms.
        """
        query = _expand_query(q) or '""'
        con = _connect(self.db_path)
        con.execute(_SCHEMA)
        try:
            # pool amplio: topics grandes (ej. JavaScript con 120 msgs) necesitan
            # muchas filas para que los recursos relevantes no queden fuera por BM25
            rows = con.execute(
                "SELECT *, bm25(messages_fts) AS rank FROM messages_fts "
                "WHERE messages_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (query, limit * 25),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        con.close()

        generic = len(_signal_terms(q)) <= 3
        # query genérica: entra una muestra amplia del topic ordenada por recurso
        per_topic = max_per_topic if not generic else max(max_per_topic, 60)

        hits_by_topic: dict[str, list] = {}
        for r in rows:
            row = dict(r)
            key = row["folder"]
            hits_by_topic.setdefault(key, []).append({
                "topic_title": row["topic_title"], "topic_id": row["topic_id"],
                "folder": key, "msg_id": row["msg_id"],
                "text": row["text"][:300], "links": _extract_links(row["text"]),
                "rank": row["rank"], "_resource": _is_resource(row["text"])})

        grouped: dict[str, dict] = {}
        for key, hits in hits_by_topic.items():
            # primero los que son recursos (link o definición), luego el resto
            hits.sort(key=lambda h: (not h["_resource"], h["rank"]))
            grouped[key] = {"topic_title": hits[0]["topic_title"],
                            "topic_id": hits[0]["topic_id"], "folder": key,
                            "hits": [{k: h[k] for k in ("msg_id", "text", "links")} for h in hits[:per_topic]]}
            if len(grouped) >= limit:
                break

        return list(grouped.values())


def _extract_links(text: str, limit: int = 5):
    """Extrae URLs reales del texto. Simple y sin dependencias."""
    out = []
    for tok in text.split():
        if tok.startswith(("http://", "https://", "www.")):
            url = tok.rstrip(".,;:)!]}")  # recortar puntuación de cierre
            if url not in out:
                out.append(url)
            if len(out) >= limit:
                break
    return out


# sinónimos técnicos español -> inglés/latín del contenido de la base.
# Clave = lema en español; valores = términos alternativos (con prefijos usables).
_SYNONYMS = {
    "vibrar": ["vibrate", "vibration"],
    "telefono": ["phone", "device"],
    "celular": ["phone", "device"],
    "pagina": ["page", "web"],
    "correr": ["run", "execute"],
    "eliminar": ["delete", "remove"],
    "crear": ["create", "make"],
    "dispositivo": ["device", "mobile"],
}

# stopwords (es/ing) que solo ensucian el ranking y matchean todo.
_STOPWORDS = {
    "que", "quien", "cual", "como", "cuando", "donde", "el", "la", "los", "las",
    "un", "una", "unos", "unas", "y", "o", "ni", "de", "del", "a", "al", "en",
    "por", "para", "con", "sin", "sobre", "entre", "hacia", "es", "ser", "son",
    "est", "esta", "este", "esto", "ese", "esa", "su", "sus", "mi", "mis", "tu",
    "puedo", "puede", "pueden", "hay", "tenes", "tiene", "quiero", "usar", "use",
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "how",
}


def _norm_token(tok: str) -> str:
    """Minúsculas sin tildes: casa con el tokenizador unicode61 de FTS5."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", tok.lower())
                   if unicodedata.category(c) != "Mn")


def _signal_terms(q: str) -> list[str]:
    """Términos de señal (no stopword) tras normalizar. Ordena genérica vs específica."""
    return [t for t in (_norm_token(w) for w in q.split()) if t and t not in _STOPWORDS]


def _is_resource(text: str) -> bool:
    """Un mensaje es 'recurso' si trae links reales, una definición con chicha,
    o es un nombre de API/tecnología seco (ej. "getScreenDetails", "vibrate api").
    """
    if _extract_links(text):
        return True
    body = text.strip()
    if len(body) >= 60:
        return True
    # nombre de API/tech: corto, sin ser una frase cotidiana (mayúscula, punto,
    # dígito, o sin espacios -> casi seguro un identificador técnico)
    if len(body) >= 3 and len(body) <= 60:
        if any(c.isupper() for c in body) or \
           any(c.isdigit() for c in body) or \
           "." in body or "(" in body or " " not in body:
            return True
        if ":" in body or "->" in body or "()" in body:
            return True
    return False


def _expand_query(q: str) -> str:
    """Convierte una query libre en una expresión MATCH de FTS5 con más recall.

    Quita stopwords, agrega sinónimos es->en del dict técnico y un prefijo
    wildcard de 4 letras para tokens largos (recupera "vibre" -> "vibrate").
    Mitiga el desacople léxico español/inglés que FTS5 no resuelve solo.
    """
    terms: list[str] = []
    for raw in q.split():
        tok = _norm_token(raw)
        if not tok or tok in _STOPWORDS:
            continue
        cands = {tok}
        if tok in _SYNONYMS:
            cands.update(_SYNONYMS[tok])
        for c in cands:
            terms.append(f'"{c}"')
            # prefijo wildcard de 4+ letras solo en tokens largos (menos ruido)
            if len(c) >= 5:
                terms.append(f"{c[:4]}*")
    return " OR ".join(terms)
