"""SPA(SvelteKit dist)フォールバックの統合テスト。

設計バグ: StaticFiles(html=True) は SPA 動的ルートを 404 にする。
`/notebooks/{id}` などへ直アクセス / リロード / ハイドレーション前クリック
すべてが index.html を返す必要がある。

加えて、ブラウザのキャッシュに古い index.html が居座って _app/immutable の
古いハッシュを要求する問題を防ぐため、index.html には no-cache を付ける。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        yield c


def _has_dist() -> bool:
    """apps/web/dist/index.html が存在しないと catch-all は何もできない。
    CI で dist がない環境ではスキップする。"""
    web_dist = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"
    return (web_dist / "index.html").is_file()


pytestmark = pytest.mark.skipif(
    not _has_dist(),
    reason="apps/web/dist/index.html missing — run npm run build first",
)


def test_root_returns_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()


def test_dynamic_notebook_route_falls_back_to_index_html(client):
    """`/notebooks/{id}` のような SvelteKit 動的ルートは index.html を返す。"""
    r = client.get("/notebooks/01KS5ASTT6FA1YQSE12B38P7X7")
    assert r.status_code == 200, r.text
    assert "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()


def test_settings_route_falls_back_to_index_html(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()


def test_nonexistent_immutable_asset_returns_index_html(client):
    """壊れた immutable URL でも 404 ではなく index.html を返す。
    挙動として SPA が "page not found" を表示できるようにする。"""
    r = client.get("/_app/immutable/nodes/ghost.js")
    assert r.status_code == 200


def test_index_html_carries_no_cache_header(client):
    """ブラウザに古い index.html が居座らないよう、Cache-Control: no-cache を付ける。
    これで再ビルドでハッシュ付きアセットが切り替わっても古い HTML が
    無効化されて新しいハッシュを要求する。"""
    r = client.get("/")
    cc = (r.headers.get("Cache-Control") or "").lower()
    assert "no-cache" in cc or "no-store" in cc


def test_dynamic_route_html_also_has_no_cache(client):
    r = client.get("/notebooks/01KS5ASTT6FA1YQSE12B38P7X7")
    cc = (r.headers.get("Cache-Control") or "").lower()
    assert "no-cache" in cc or "no-store" in cc


def test_api_routes_still_work(client):
    """catch-all が後勝ちで API を飲み込まないこと。"""
    r = client.get("/api/notebooks")
    assert r.status_code == 200


def test_api_404_returns_json_not_html(client):
    """`/api/...` で専用ルートに無いパスは 404(JSON)を返す。SPA fallback で
    HTML を返すと API クライアントが混乱するため。"""
    r = client.get("/api/this-does-not-exist")
    assert r.status_code == 404
    # HTML ではない(JSON or プレーンテキスト の detail)
    assert "<!doctype html>" not in r.text.lower()
    assert "<html" not in r.text.lower()


def test_path_traversal_is_defended(client):
    """`..` を含むパスは defense-in-depth で index.html へフォールバックさせる
    (実ファイル配信に到達させない)。"""
    r = client.get("/../../etc/passwd")
    # Starlette 側で正規化されてルートが一致しないか、index.html が返る。
    # いずれにせよ機密ファイル内容には到達しない。
    assert r.status_code in (200, 404)
    assert "root:" not in r.text
