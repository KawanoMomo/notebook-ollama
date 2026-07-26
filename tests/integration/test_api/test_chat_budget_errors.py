"""チャットのコンテキスト予算エラーのハンドリング(実機FB 2026-07-26)。

実機で「図画像の生成後にネットワークエラー」と報告された事象の正体は2段:
1. vision対応チャットモデル(llava等)は Modelfile の num_ctx が小さく、
   既定の応答予算2048と組むと質問内容に関わらず必ず
   GENERATION_CONTEXT_OVERFLOW になる(SSE開始前に検査できる)
2. SSE 開始後に AppError が漏れると "response already started" の500に化け、
   FE には生のネットワークエラーしか見えない(error イベントで流すべき)
"""
from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    app = create_app()
    with TestClient(app) as c:
        yield c


def _conv(client) -> tuple[str, str]:
    nb_id = client.post(
        "/api/notebooks", json={"name": "N", "default_model": "llava:7b"}
    ).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    return nb_id, conv_id


def test_tiny_model_ctx_returns_400_before_sse(client):
    """num_ctx=2048 x 応答予算2048 → available<0。SSE前に400+日本語で弾く。"""
    nb_id, conv_id = _conv(client)
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(200, json={"parameters": "num_ctx 2048"})
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
    assert r.status_code == 400
    body = r.json()
    assert "num_ctx" in body["error"]["message"]
    assert body["error"]["remediation"] is not None


def test_midstream_apperror_becomes_sse_error_event(client):
    """SSE開始後のAppErrorは error イベントとして流れ、500に化けない。"""
    from core.exceptions import AppError, ErrorCode

    nb_id, conv_id = _conv(client)

    class BoomGeneration:
        async def run(self, **kwargs):
            raise AppError(
                ErrorCode.GENERATION_CONTEXT_OVERFLOW,
                "question alone exceeds context budget",
            )
            yield  # pragma: no cover

    ctx = client.app.state.ctx
    ctx.generation = BoomGeneration()
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(
            return_value=httpx.Response(200, json={"parameters": "num_ctx 8192"})
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
    assert r.status_code == 200  # SSEは開始される
    assert "event: error" in r.text
    assert "context" in r.text or "コンテキスト" in r.text


def test_missing_model_returns_404_with_remediation(client):
    """実機FB 2026-07-26: 選択済みモデルがOllamaから削除済み/未取得だと
    生の英語メッセージ(remediation無し)がFEに生JSONで出て対処が分からない。
    SSE前に日本語メッセージ+直す場所(ノートのモデル/既定モデル/ollama pull)
    を返すこと。"""
    nb_id, conv_id = _conv(client)
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(return_value=httpx.Response(404))
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
    assert r.status_code == 404
    body = r.json()["error"]
    assert "見つかりません" in body["message"]
    assert "llava:7b" in body["message"]  # どのモデルかを明示
    # ノートブック個別設定が原因だと分かること(実機FB第2報: 全体既定を
    # 切り替えても直らない理由が見えなかった)
    assert "このノートブックに設定されたモデル" in body["message"]
    assert "ollama pull" in body["remediation"]
    assert "このノートのモデル" in body["remediation"]


def test_missing_global_default_model_points_to_settings(client):
    """ノート個別モデル未設定時は全体既定が使われる。その全体既定が
    Ollama に無い場合は、設定画面のどこを直すかを明示すること。"""
    nb_id = client.post("/api/notebooks", json={"name": "N2"}).json()["id"]
    conv_id = client.post(f"/api/notebooks/{nb_id}/conversations").json()["id"]
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(return_value=httpx.Response(404))
        router.get("http://fake/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
    assert r.status_code == 404
    body = r.json()["error"]
    assert "全体既定モデル" in body["message"]
    assert "設定→モデル・Ollama" in body["remediation"]


def test_missing_model_suggests_similar_existing_name(client):
    """実機FB第2報:「一覧に表示されているのに not found」はタグ部分違い等の
    名前ズレで起きうる。Ollama 実在の類似名(タグ違い・大小文字違い)を
    「こちらを選択し直してください」と提示すること。"""
    nb_id, conv_id = _conv(client)  # ノート個別モデル llava:7b
    with respx.mock() as router:
        router.post("http://fake/api/show").mock(return_value=httpx.Response(404))
        router.get("http://fake/api/tags").mock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "llava:latest"}, {"name": "qwen2.5:14b"}]}
            )
        )
        r = client.post(
            f"/api/notebooks/{nb_id}/conversations/{conv_id}/messages",
            json={"content": "質問", "source_ids": ["SRC_DUMMY"]},
        )
    assert r.status_code == 404
    body = r.json()["error"]
    assert "llava:latest が存在します" in body["remediation"]
    assert "qwen2.5:14b" not in body["remediation"]  # 無関係モデルは提示しない
    assert "ollama pull" not in body["remediation"]  # 候補ありなら pull 案内は不要
