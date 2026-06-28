"""録音オフライン変換の停止(協調キャンセル)テスト。

RecordingPipeline.request_cancel(source_id) を立てると、run() はステップ境界 /
埋め込みループで ConversionCancelled を送出し、status=error("...停止...") にして
握りつぶす(background task なので再送出しない)。停止フラグは run 終了時にクリア
され、後続の再試行が誤って事前キャンセル状態にならないこと。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.transcriber import TranscriptSegment
from core.storage.database import migrate


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    c.execute("INSERT INTO notebooks(id,name,created_at,updated_at) VALUES('nb','n','t','t')")
    c.execute(
        "INSERT INTO sources(id,notebook_id,kind,status,created_at,updated_at) "
        "VALUES('src','nb','recording','pending','t','t')"
    )
    return c


class _Tx:
    """mic 1 セグメントだけ返す。on_call フックで transcribe 呼び出し時に副作用を起こせる。"""

    def __init__(self, on_call=None):
        self._on = on_call
        self.called = 0

    def transcribe(self, wav, *, channel, speaker_id, language="ja", session_id=""):
        self.called += 1
        if self._on:
            self._on()
        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="mic",
                start_ms=0, end_ms=1000, speaker_id=speaker_id,
                text="テスト発話", language="ja",
            )
        ]


class _Diar:
    def diarize(self, wav):
        return []


class _Ollama:
    def __init__(self, on_embed=None):
        self.embed_calls = 0
        self._on_embed = on_embed

    async def embed(self, *, model, text):
        self.embed_calls += 1
        if self._on_embed:
            self._on_embed()
        return [0.1, 0.2, 0.3]

    async def generate(self, *, model, prompt, options=None):
        # 校正: 「番号. テキスト」行をそのままエコー。
        out = []
        for raw in prompt.splitlines():
            s = raw.strip()
            if s and s[0].isdigit() and "." in s:
                num, _, rest = s.partition(".")
                if num.isdigit():
                    out.append(f"{num}. {rest.strip()}")
        return "\n".join(out)


class _VS:
    def __init__(self):
        self.upserts: list = []

    def upsert(self, vectors):
        self.upserts.extend(list(vectors))


def _pipeline(conn, vs, ollama):
    return RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=ollama,
            embedding_model="bge-m3", broker=None,
        )
    )


async def _run(pipeline, tx):
    await pipeline.run(
        source_id="src", notebook_id="nb",
        mic_wav=Path("mic.wav"), system_wav=None,
        transcriber=tx, diarizer=_Diar(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7, auto_title_enabled=False,
    )


async def test_cancel_before_run_aborts_immediately():
    conn = _conn()
    vs = _VS()
    pipeline = _pipeline(conn, vs, _Ollama())
    tx = _Tx()
    pipeline.request_cancel("src")

    await _run(pipeline, tx)  # must not raise

    row = conn.execute("SELECT status, error_msg FROM sources WHERE id='src'").fetchone()
    assert row["status"] == "error"
    assert "停止" in (row["error_msg"] or "")
    assert tx.called == 0, "transcribe must not run when cancelled before start"
    assert not vs.upserts
    assert pipeline.is_cancelled("src") is False, "flag must be cleared for clean retry"


async def test_cancel_during_processing_skips_embed_and_upsert():
    conn = _conn()
    vs = _VS()
    pipeline = _pipeline(conn, vs, _Ollama())
    # transcribe 実行時にユーザーが停止を押した想定。
    tx = _Tx(on_call=lambda: pipeline.request_cancel("src"))

    await _run(pipeline, tx)  # must not raise

    row = conn.execute("SELECT status, error_msg FROM sources WHERE id='src'").fetchone()
    assert row["status"] == "error"
    assert "停止" in (row["error_msg"] or "")
    assert tx.called == 1
    assert pipeline._deps.ollama.embed_calls == 0, "must bail before the embed loop"
    assert not vs.upserts
    assert pipeline.is_cancelled("src") is False


async def test_cancel_during_embed_loop_persists_nothing():
    conn = _conn()
    vs = _VS()
    ollama = _Ollama()
    pipeline = _pipeline(conn, vs, ollama)
    # 埋め込み 1 回目でユーザーが停止 → ループ/永続化前のチェックで中断。
    ollama._on_embed = lambda: pipeline.request_cancel("src")
    tx = _Tx()

    await _run(pipeline, tx)  # must not raise

    row = conn.execute("SELECT status, error_msg FROM sources WHERE id='src'").fetchone()
    assert row["status"] == "error"
    assert "停止" in (row["error_msg"] or "")
    assert ollama.embed_calls >= 1
    assert not vs.upserts, "no partial vectors persisted on cancel"
    chunk_rows = conn.execute("SELECT COUNT(*) c FROM chunks WHERE source_id='src'").fetchone()
    assert chunk_rows["c"] == 0, "no partial chunks persisted on cancel"
    assert pipeline.is_cancelled("src") is False
