"""Demo/self-check del índice FTS5. No usa frameworks, solo asserts.

    uv run plugins/search/index.py
"""

import json
import os
import tempfile
from pathlib import Path

from plugins.search.index import SearchIndex


def _write_topic(root: Path, folder: str, topic_id: int, title: str, texts: list[str]):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(
        json.dumps({
            "topic_id": topic_id, "topic_title": title,
            "messages": [{"id": i, "text": t} for i, t in enumerate(texts)],
        }), encoding="utf-8")
    return d


def demo():
    tmp = Path(tempfile.mkdtemp())
    _write_topic(tmp, "1_Kubernetes", 1, "Kubernetes",
                 ["instalá minikube", "api de vibrar el dispositivo",
                  "guía: https://example.com/securing-kubernetes"])
    _write_topic(tmp, "2_Python", 2, "Python",
                 ["esto es sobre kubernetes avanzado", "recursos gratis"])
    _write_topic(tmp, "_ignored", 3, "x", [])  # no es data.json válido

    idx = SearchIndex(db_path=tmp / "t.db", topics_dir=tmp)
    total = idx.build_if_stale()
    assert total == 5, total

    hits = idx.search("kubernetes")
    assert len(hits) == 2, hits  # matchea 2 topics distintos
    assert {h["folder"] for h in hits} == {"1_Kubernetes", "2_Python"}, hits

    # priorización: el hit con link debe venir antes en su topic
    k = next(t for t in hits if t["folder"] == "1_Kubernetes")
    assert k["hits"][0]["links"] == ["https://example.com/securing-kubernetes"], k

    # el match arma query con OR de tokens; 'vibrar' debería dar 1 topic
    hits2 = idx.search("vibrar dispositivo")
    assert len(hits2) == 1 and hits2[0]["folder"] == "1_Kubernetes", hits2

    print("OK: index/search works; kw='kubernetes' ->", len(hits), "topics (links priorizados)")


if __name__ == "__main__":
    demo()
