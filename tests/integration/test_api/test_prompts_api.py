"""POST/PUT/DELETE /api/prompts/* の統合テスト。

設計: docs/specs/2026-06-26-prompt-injection-design.md §4, §6.1, §7.2
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__ENDPOINT", "http://fake")
    with TestClient(create_app()) as c:
        c._tmp_path = tmp_path  # type: ignore[attr-defined]
        yield c


# --- GET (defaults) ------------------------------------------------------


def test_get_prompts_returns_defaults_when_empty(client):
    r = client.get("/api/prompts")
    assert r.status_code == 200
    body = r.json()
    assert len(body["fixed"]) == 3
    assert all(
        s["title"] == "" and s["body"] == "" and s["icon_url"] is None for s in body["fixed"]
    )
    assert body["dropdown"] == []


# --- 固定スロット PUT/DELETE ---------------------------------------------


def test_put_fixed_slot_persists(client):
    r = client.put(
        "/api/prompts/fixed/0",
        json={"title": "要約", "body": "3行で要約"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fixed"][0]["title"] == "要約"
    assert body["fixed"][0]["body"] == "3行で要約"
    # 永続化確認(GET 再取得)
    r2 = client.get("/api/prompts")
    assert r2.json()["fixed"][0]["title"] == "要約"


def test_put_fixed_slot_rejects_out_of_range(client):
    r = client.put("/api/prompts/fixed/3", json={"title": "x", "body": "y"})
    assert r.status_code == 400


def test_put_fixed_slot_rejects_title_overflow(client):
    r = client.put(
        "/api/prompts/fixed/0",
        json={"title": "x" * 101, "body": "y"},
    )
    assert r.status_code == 422  # pydantic validation


def test_delete_fixed_slot_clears_text_and_icon(client):
    client.put("/api/prompts/fixed/0", json={"title": "A", "body": "B"})
    r = client.delete("/api/prompts/fixed/0")
    assert r.status_code == 200
    body = r.json()
    assert body["fixed"][0]["title"] == ""
    assert body["fixed"][0]["body"] == ""
    assert body["fixed"][0]["icon_url"] is None


# --- プルダウン CRUD ----------------------------------------------------


def test_post_dropdown_appends_and_returns_id(client):
    r = client.post("/api/prompts/dropdown", json={"title": "翻訳", "body": "英語に"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "翻訳"
    assert len(body["id"]) == 36  # uuid v4


def test_put_dropdown_edits_in_place(client):
    item = client.post(
        "/api/prompts/dropdown", json={"title": "翻訳", "body": "英語に"}
    ).json()
    r = client.put(
        f"/api/prompts/dropdown/{item['id']}",
        json={"title": "翻訳v2", "body": "日本語に"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "翻訳v2"


def test_put_dropdown_unknown_id_returns_404(client):
    r = client.put(
        "/api/prompts/dropdown/does-not-exist", json={"title": "x", "body": "y"}
    )
    assert r.status_code == 404


def test_delete_dropdown_removes_item(client):
    a = client.post(
        "/api/prompts/dropdown", json={"title": "A", "body": "x"}
    ).json()
    b = client.post(
        "/api/prompts/dropdown", json={"title": "B", "body": "y"}
    ).json()
    r = client.delete(f"/api/prompts/dropdown/{a['id']}")
    assert r.status_code == 204
    rest = client.get("/api/prompts").json()["dropdown"]
    assert [d["id"] for d in rest] == [b["id"]]


def test_dropdown_limit_returns_400_on_101st(client):
    for i in range(100):
        r = client.post(
            "/api/prompts/dropdown", json={"title": f"t{i}", "body": "x"}
        )
        assert r.status_code == 201, f"#{i}: {r.text}"
    r = client.post(
        "/api/prompts/dropdown", json={"title": "t100", "body": "x"}
    )
    assert r.status_code == 400


# --- 並び替え -----------------------------------------------------------


def test_put_dropdown_order_with_complete_ids_succeeds(client):
    a = client.post(
        "/api/prompts/dropdown", json={"title": "A", "body": "x"}
    ).json()
    b = client.post(
        "/api/prompts/dropdown", json={"title": "B", "body": "x"}
    ).json()
    c = client.post(
        "/api/prompts/dropdown", json={"title": "C", "body": "x"}
    ).json()
    r = client.put(
        "/api/prompts/dropdown/order", json={"ids": [c["id"], a["id"], b["id"]]}
    )
    assert r.status_code == 200
    rest = client.get("/api/prompts").json()["dropdown"]
    assert [d["id"] for d in rest] == [c["id"], a["id"], b["id"]]


def test_put_dropdown_order_with_missing_id_returns_400(client):
    a = client.post(
        "/api/prompts/dropdown", json={"title": "A", "body": "x"}
    ).json()
    client.post("/api/prompts/dropdown", json={"title": "B", "body": "x"})
    r = client.put("/api/prompts/dropdown/order", json={"ids": [a["id"]]})
    assert r.status_code == 400


# --- 画像アップロード ---------------------------------------------------


_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _png(size: int = 1024) -> bytes:
    # ヘッダ 16 byte + padding。PIL に依存しないシンプルな valid PNG header。
    return _PNG_HEADER + b"\x00" * max(0, size - len(_PNG_HEADER))


def test_post_icon_accepts_png_and_returns_icon_url(client):
    data = _png(2000)
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("icon.png", io.BytesIO(data), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    icon = body["fixed"][0]["icon_url"]
    assert icon is not None
    assert icon.startswith("/api/prompts/icons/")
    assert icon.endswith(".png")

    # アイコンファイルがディスク上に作られている
    tmp_path: Path = client._tmp_path  # type: ignore[attr-defined]
    icons_dir = tmp_path / "prompt-icons"
    assert icons_dir.is_dir()
    assert any(p.suffix == ".png" for p in icons_dir.iterdir())


def test_post_icon_rejects_over_200kb(client):
    data = _png(200 * 1024 + 1)
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("big.png", io.BytesIO(data), "image/png")},
    )
    assert r.status_code == 413


def test_post_icon_rejects_mime_mismatch(client):
    # PNG 拡張子だが GIF magic bytes
    data = b"GIF89a" + b"\x00" * 100
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("fake.png", io.BytesIO(data), "image/png")},
    )
    assert r.status_code == 415


def test_post_icon_rejects_svg_with_script(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("xss.svg", io.BytesIO(svg), "image/svg+xml")},
    )
    assert r.status_code == 400


def test_post_icon_accepts_clean_svg(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>'
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("ok.svg", io.BytesIO(svg), "image/svg+xml")},
    )
    assert r.status_code == 200, r.text


def test_get_icon_returns_file_and_rejects_traversal(client):
    data = _png(500)
    r = client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("icon.png", io.BytesIO(data), "image/png")},
    )
    icon_url = r.json()["fixed"][0]["icon_url"]
    # 正規 GET
    r2 = client.get(icon_url)
    assert r2.status_code == 200
    assert r2.content.startswith(_PNG_HEADER[:8])
    # path traversal: Starlette が `..%2F` を `/` に正規化してルートが
    # 一致しないため 404、もしくはルーターに届いて UUID 正規表現で 400。
    # どちらの経路でもファイルへは到達しない = ディフェンスとして成立。
    r3 = client.get("/api/prompts/icons/..%2F..%2Fetc%2Fpasswd")
    assert r3.status_code in (400, 404)
    # 形式は通るが存在しない正規 UUID も 404
    r4 = client.get(
        "/api/prompts/icons/00000000-0000-0000-0000-000000000000.png"
    )
    assert r4.status_code == 404


def test_delete_icon_removes_only_icon(client):
    client.put("/api/prompts/fixed/0", json={"title": "A", "body": "B"})
    client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("icon.png", io.BytesIO(_png(500)), "image/png")},
    )
    r = client.delete("/api/prompts/fixed/0/icon")
    assert r.status_code == 200
    body = r.json()
    assert body["fixed"][0]["icon_url"] is None
    assert body["fixed"][0]["title"] == "A"  # text は維持


def test_delete_fixed_slot_also_deletes_icon_file(client):
    client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("icon.png", io.BytesIO(_png(500)), "image/png")},
    )
    tmp_path: Path = client._tmp_path  # type: ignore[attr-defined]
    icons = list((tmp_path / "prompt-icons").iterdir())
    assert len(icons) == 1
    r = client.delete("/api/prompts/fixed/0")
    assert r.status_code == 200
    # ファイルが消えている
    icons_after = list((tmp_path / "prompt-icons").iterdir())
    assert icons_after == []


def test_post_icon_replaces_previous_icon_file(client):
    """旧画像は新画像で置換破棄される(設計 §4.1)。"""
    client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("a.png", io.BytesIO(_png(500)), "image/png")},
    )
    client.post(
        "/api/prompts/fixed/0/icon",
        files={"file": ("b.png", io.BytesIO(_png(800)), "image/png")},
    )
    tmp_path: Path = client._tmp_path  # type: ignore[attr-defined]
    icons = list((tmp_path / "prompt-icons").iterdir())
    assert len(icons) == 1  # 1 つだけ残る
