import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.storage import sources_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _create_nb(client, name="音声配信テスト") -> str:
    r = client.post("/api/notebooks", json={"name": name})
    return r.json()["id"]


def _seed_recording_source(client, notebook_id: str) -> str:
    """Create a recording-kind source row and return its id."""
    ctx = client.app.state.ctx
    src = sources_repo.create_source(
        ctx.conn, notebook_id=notebook_id, kind="recording", title=None, origin="録音"
    )
    return src.id


def _write_mic_wav(client, source_id: str, data: bytes) -> None:
    ctx = client.app.state.ctx
    base = ctx.config.sources_dir / source_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "mic.wav").write_bytes(data)


def test_audio_range_request_returns_206_partial(client):
    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)
    payload = bytes(range(256)) * 4  # 1024 bytes of arbitrary content
    _write_mic_wav(client, sid, payload)

    r = client.get(
        f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mic",
        headers={"Range": "bytes=0-9"},
    )
    assert r.status_code == 206, r.text
    assert r.headers["Content-Range"] == f"bytes 0-9/{len(payload)}"
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers["Content-Length"] == "10"
    assert len(r.content) == 10
    assert r.content == payload[0:10]


def test_audio_no_range_returns_200_full_body(client):
    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)
    payload = b"\x52\x49\x46\x46" + bytes(range(96))  # tiny RIFF-ish header + bytes
    _write_mic_wav(client, sid, payload)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mic")
    assert r.status_code == 200, r.text
    assert r.content == payload
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers.get("content-type", "").startswith("audio/wav")


def test_audio_missing_channel_file_returns_404(client):
    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)
    _write_mic_wav(client, sid, b"only mic exists here")

    # system.wav / system.m4a were never written -> 404
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=system")
    assert r.status_code == 404


def test_audio_source_in_other_notebook_returns_404(client):
    nb = _create_nb(client)
    other = _create_nb(client, name="別ノート")
    sid = _seed_recording_source(client, other)
    _write_mic_wav(client, sid, b"belongs to other notebook")

    # request under the wrong notebook id -> 404
    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mic")
    assert r.status_code == 404

    # unknown source id -> 404 as well
    r2 = client.get(f"/api/notebooks/{nb}/sources/does-not-exist/audio?channel=mic")
    assert r2.status_code == 404


def _write_channel(client, source_id: str, channel: str, data: bytes) -> None:
    ctx = client.app.state.ctx
    base = ctx.config.sources_dir / source_id
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{channel}.wav").write_bytes(data)


# ---------------------------------------------------------------------------
# channel=mix (2026-07-04 実機フィードバック: ミックス音声を主動線で聴きたい)
# ---------------------------------------------------------------------------


def test_audio_mix_with_single_channel_serves_that_channel(client):
    """片チャンネルしか無い録音では mix はそのチャンネルをそのまま配信する
    (ffmpeg 不要のフォールバック)。"""
    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)
    payload = b"mic-only-audio-bytes"
    _write_channel(client, sid, "mic", payload)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mix")
    assert r.status_code == 200, r.text
    assert r.content == payload


def test_audio_mix_serves_cached_mix_file_without_regeneration(client):
    """両チャンネルが存在し、より新しい mix キャッシュがあればそれを配信する
    (ffmpeg を起動しない)。"""
    import time

    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)
    _write_channel(client, sid, "mic", b"mic-bytes")
    _write_channel(client, sid, "system", b"system-bytes")
    time.sleep(0.05)  # mix を最も新しい mtime にする
    mixed = b"pre-mixed-cache-bytes"
    ctx = client.app.state.ctx
    (ctx.config.sources_dir / sid / "mix.m4a").write_bytes(mixed)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mix")
    assert r.status_code == 200, r.text
    assert r.content == mixed


def test_audio_mix_without_any_audio_returns_404(client):
    nb = _create_nb(client)
    sid = _seed_recording_source(client, nb)

    r = client.get(f"/api/notebooks/{nb}/sources/{sid}/audio?channel=mix")
    assert r.status_code == 404
