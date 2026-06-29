import asyncio
import sqlite3

from core.retrieval.search import RetrievalService
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import migrate
from core.storage.vector_store import SearchHit


class _FakeVS:
    def search(self, *, query, notebook_id, limit, source_ids=None):
        return [SearchHit(id="c1", score=0.9, notebook_id="nb", source_id="src",
                          source_kind="recording", page=None, heading_path=None, ord=0,
                          start_ms=12340, end_ms=12980, speaker="相手1", channel="system")]


class _FakeOllama:
    async def embed(self, *, model, text):
        return [0.0, 0.0, 0.0]


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute("INSERT INTO sources(id,notebook_id,kind,title,status,created_at,updated_at) "
              "VALUES('src','nb','recording','録音1','ready','t','t')")
    insert_chunks(c, [ChunkRecord(id="c1", source_id="src", notebook_id="nb", ord=0,
                                  page=None, heading_path=None, text="x", token_count=1,
                                  start_ms=12340, end_ms=12980, speaker="相手1")])
    return c


def test_retrieved_chunk_has_timecode():
    svc = RetrievalService(conn=_conn(), vector_store=_FakeVS(),
                           ollama=_FakeOllama(), embedding_model="bge-m3")
    out = asyncio.run(svc.search(notebook_id="nb", query="q", limit=1))
    assert out[0].start_ms == 12340
    assert out[0].end_ms == 12980
    assert out[0].speaker == "相手1"
    assert out[0].channel == "system"
