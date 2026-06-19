import json

import pytest

from apps.api.dependencies import build_context
from core.config import AppConfig
from core.settings_store import settings_path


def _make_config(tmp_path):
    return AppConfig(data_dir=tmp_path)


def test_default_dim_when_no_settings_and_no_collection(tmp_path):
    cfg = _make_config(tmp_path)
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 1024
    finally:
        ctx.vector_store.close()


def test_dim_from_settings_json_when_no_collection(tmp_path):
    cfg = _make_config(tmp_path)
    cfg.ensure_dirs()
    settings_path(cfg.data_dir).write_text(
        json.dumps({"ollama": {"embedding_dim": 768}}), encoding="utf-8"
    )
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 768
    finally:
        ctx.vector_store.close()


def test_existing_collection_dim_wins_over_settings(tmp_path):
    # 既存 collection を 512 次元で先に作る
    from core.storage.vector_store import VectorStore

    pre = VectorStore(path=tmp_path / "qdrant", dim=512)
    pre.ensure_collection()
    pre.close()

    cfg = _make_config(tmp_path)
    cfg.ensure_dirs()
    # settings は別の dim を主張するが、既存 collection を優先する
    settings_path(cfg.data_dir).write_text(
        json.dumps({"ollama": {"embedding_dim": 768}}), encoding="utf-8"
    )
    ctx = build_context(cfg)
    try:
        assert ctx.vector_store.collection_dim() == 512
    finally:
        ctx.vector_store.close()
