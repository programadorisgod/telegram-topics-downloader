"""Demo/self-check de la orquestación AI sin llamar a DeepSeek real.

    uv run python -m plugins.ai.ai_demo
"""

import json
import tempfile
from pathlib import Path

from plugins.ai import AiPlugin
from plugins.search import SearchIndex
from providers.base import register, ChatProvider


@register
class _FakeProvider(ChatProvider):
    name = "fake"
    def chat(self, system, messages, **kwargs):
        return "RESPUESTA-FAKE-basada-en-contexto"


def _write_topic(root, folder, tid, title, texts):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "data.json").write_text(json.dumps({
        "topic_id": tid, "topic_title": title,
        "messages": [{"id": i, "text": t} for i, t in enumerate(texts)],
    }), encoding="utf-8")


def demo():
    tmp = Path(tempfile.mkdtemp())
    _write_topic(tmp, "1_Kubernetes", 1, "Kubernetes", ["instalá minikube para kubernetes local"])
    idx = SearchIndex(db_path=tmp / "t.db", topics_dir=tmp)
    idx.build(force=True)

    ai = AiPlugin(search=idx)
    res = ai.ask("kubernetes", provider=_FakeProvider())
    assert res["answer"] == "RESPUESTA-FAKE-basada-en-contexto", res
    assert len(res["topics"]) == 1 and res["topics"][0]["folder"] == "1_Kubernetes", res

    res2 = ai.ask("kubernetes", provider=_FakeProvider())
    assert res2["cached"] is True, res2
    print("OK: ai orchestration works, cache hits")

    # provider no registrado -> debe fallar limpio
    from providers.base import get_provider
    try:
        get_provider("no-existe")
        raise AssertionError("debió fallar")
    except ValueError:
        pass
    print("OK: provider resolution falla limpio")


if __name__ == "__main__":
    demo()
