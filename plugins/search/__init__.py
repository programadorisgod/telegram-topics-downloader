"""Plugin search: expone el índice FTS5 como endpoints HTTP."""

import time

from fastapi import APIRouter, Query

from plugins.base import Plugin
from plugins.search.index import SearchIndex


class SearchPlugin(Plugin):
    name = "search"

    def __init__(self):
        self.index = SearchIndex()

    def build(self):
        t0 = time.time()
        total = self.index.build_if_stale()
        print(f"[search] índice listo ({total} msgs, {time.time()-t0:.2f}s)")

    def router(self):
        r = APIRouter(prefix="/api/search", tags=["search"])

        @r.get("")
        def search(q: str = Query(..., min_length=1)):
            results = self.index.search(q)
            return {"query": q, "count": len(results), "results": results}

        @r.post("/rebuild")
        def rebuild():
            total = self.index.build(force=True)
            return {"rebuilt": True, "messages": total}

        return r


plugin = SearchPlugin()
