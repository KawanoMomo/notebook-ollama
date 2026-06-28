from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import build_context
from apps.api.main import create_app
from core.config import AppConfig
from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.vector_store import ChunkVector, VectorStore


def test_apply_overrides_applies_ollama_default_model(memory_data_dir):
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "llama3.1:8b",
                    "embedding_model": "bge-m3",
                    "embedding_dim": 1024,
                }
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app()) as client:
        ollama = client.get("/api/settings").json()["ollama"]
        assert ollama["default_model"] == "llama3.1:8b"
        # embedding_model は保持される(本タスクでは default_model のみ反映対象)。
        assert ollama["embedding_model"] == "bge-m3"


def test_invalid_ollama_override_does_not_crash_startup(memory_data_dir):
    """型不正な ollama オーバーライドで起動をクラッシュさせず既定で続行する。"""
    (memory_data_dir / "settings.json").write_text(
        '{"ollama": {"default_model": 12345}}', encoding="utf-8"
    )
    with TestClient(create_app()) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        # 既定モデルに戻る(core/config.py OllamaSettings.default_model)。
        assert r.json()["ollama"]["default_model"] == "qwen2.5:14b"


class _CapturingGateway:
    """embed に渡る model 名を記録する fake gateway。"""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.embed_models: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.embed_models.append(model)
        return [0.1] * self.dim


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_embedding_model_restored_on_restart(memory_data_dir):
    """Critical 回帰: 埋め込み切替後に再起動しても embedding_model/dim が復元され、
    実行時 getter が切替済みモデルで embed を呼ぶこと。

    バグ: apply_overrides が default_model のみ適用していたため、再起動で
    embedding_model が config 既定 bge-m3(1024)へ巻き戻り、768 次元 collection に
    1024 次元ベクトルを投げて全検索・全取込が壊れていた。
    """
    switched_model = "nomic-embed-text"
    new_dim = 768

    # 切替後の永続状態を模す: settings.json に切替済み埋め込み + new_dim の collection。
    (memory_data_dir / "settings.json").write_text(
        json.dumps(
            {
                "ollama": {
                    "default_model": "qwen2.5:14b",
                    "embedding_model": switched_model,
                    "embedding_dim": new_dim,
                }
            }
        ),
        encoding="utf-8",
    )
    # new_dim 次元の既存 collection を seed(_resolve_embedding_dim がこれを採用)。
    seed_cfg = AppConfig(data_dir=memory_data_dir)
    seed_vs = VectorStore(path=seed_cfg.qdrant_path, dim=new_dim)
    seed_vs.ensure_collection()
    seed_vs.close()

    # ---- 再起動相当: main.py lifespan と同じ apply_overrides -> build_context 順 ----
    from core.settings_store import apply_overrides

    config = AppConfig(data_dir=memory_data_dir)
    apply_overrides(config)
    ctx = build_context(config)
    try:
        # 1. cfg.ollama.embedding_model / dim が切替値へ復元されている
        assert ctx.config.ollama.embedding_model == switched_model
        assert ctx.config.ollama.embedding_dim == new_dim
        # 2. collection は new_dim のまま(bge-m3 の 1024 に戻っていない)
        assert ctx.vector_store.collection_dim() == new_dim

        # 3. 実行時 embed 経路が切替済みモデル名を使うこと(dim mismatch を起こさない)。
        nb = notebooks_repo.create_notebook(ctx.conn, name="nb")
        src = sources_repo.create_source(ctx.conn, notebook_id=nb.id, kind="md")
        insert_chunks(
            ctx.conn,
            [
                ChunkRecord(
                    id="c1", source_id=src.id, notebook_id=nb.id, ord=0,
                    page=None, heading_path=None, text="hello", token_count=1,
                )
            ],
        )
        ctx.conn.commit()
        ctx.vector_store.upsert(
            [
                ChunkVector(
                    id="c1", vector=[0.1] * new_dim, notebook_id=nb.id,
                    source_id=src.id, source_kind="md", page=None,
                    heading_path=None, ord=0,
                )
            ]
        )
        fake = _CapturingGateway(dim=new_dim)
        # RetrievalService は build_context 時の gateway を自身に束ねるため直接差替える
        # (ctx.ollama 差替だけでは retrieval 経路に届かない)。getter は cfg を参照する。
        ctx.retrieval._ollama = fake
        await ctx.retrieval.search(notebook_id=nb.id, query="hi", limit=5)
        assert fake.embed_models == [switched_model]
    finally:
        ctx.vector_store.close()
        ctx.conn.close()
