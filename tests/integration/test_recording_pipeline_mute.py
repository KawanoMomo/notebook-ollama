"""録音オフラインパイプラインのミュート区間除外 統合テスト(全依存 fake)。

mute_intervals.json でミュート窓を指定した録音ディレクトリでパイプラインを走らせ、
ミュート窓と重なる STT セグメントが最終 chunks / ベクトルに含まれないこと、窓外の
セグメントは残ることを確認する。古い録音(JSON 無し)が従来どおり動くことも確認する。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.recording.diarizer import SpeakerSegment
from core.recording.recording_pipeline import RecordingPipeline, RecordingPipelineDeps
from core.recording.transcriber import TranscriptSegment
from core.storage.database import migrate


class FakeTranscriber:
    """mic / system それぞれ 2 セグメント(既知タイムコード)を返す fake。

    mic:    0-1000   "おはようございます"
            4000-5000 "田中さんお願いします"
    system: 1000-2000 "はい田中です"
            6000-7000 "鈴木でございます"
    """

    def transcribe(self, wav_path, *, channel, speaker_id, language="ja", session_id=""):
        if channel == "mic":
            return [
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=0, end_ms=1000, speaker_id=speaker_id,
                    text="おはようございます", language="ja",
                ),
                TranscriptSegment(
                    id=None, session_id=session_id, channel="mic",
                    start_ms=4000, end_ms=5000, speaker_id=speaker_id,
                    text="マイクのミュート対象", language="ja",
                ),
            ]
        return [
            TranscriptSegment(
                id=None, session_id=session_id, channel="system",
                start_ms=1000, end_ms=2000, speaker_id=speaker_id,
                text="システムの通常発言", language="ja",
            ),
            TranscriptSegment(
                id=None, session_id=session_id, channel="system",
                start_ms=6000, end_ms=7000, speaker_id=speaker_id,
                text="システムのミュート対象", language="ja",
            ),
        ]


class FakeDiarizer:
    def diarize(self, wav_path):
        return [
            SpeakerSegment(speaker_id="spk_000", start_ms=900, end_ms=2100),
            SpeakerSegment(speaker_id="spk_001", start_ms=5900, end_ms=7100),
        ]


class FakeOllama:
    async def embed(self, *, model, text):
        return [0.1, 0.2, 0.3]

    async def generate(self, *, model, prompt, options=None):
        # 校正: 番号付き行をそのままエコー(件数保存)。name-inference は無効で使う。
        lines = []
        for raw in prompt.splitlines():
            stripped = raw.strip()
            if stripped and stripped[0].isdigit() and "." in stripped:
                num, _, rest = stripped.partition(".")
                if num.isdigit():
                    lines.append(f"{num}. {rest.strip()}")
        return "\n".join(lines)


class FakeVectorStore:
    def __init__(self):
        self.upserts: list = []

    def ensure_collection(self):
        pass

    def upsert(self, vectors):
        self.upserts.extend(list(vectors))


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


def _pipeline(conn, vs):
    return RecordingPipeline(
        deps=RecordingPipelineDeps(
            conn=conn, vector_store=vs, ollama=FakeOllama(),
            embedding_model="bge-m3", broker=None,
        )
    )


async def _run(conn, vs, mic_wav, system_wav):
    await _pipeline(conn, vs).run(
        source_id="src", notebook_id="nb",
        mic_wav=mic_wav, system_wav=system_wav,
        transcriber=FakeTranscriber(), diarizer=FakeDiarizer(),
        model="qwen3", diarization_enabled=False, name_inference_enabled=False,
        name_threshold=0.7,
    )


def _chunk_texts(conn) -> list[str]:
    rows = conn.execute(
        "SELECT text FROM chunks WHERE source_id='src' ORDER BY ord"
    ).fetchall()
    return [r["text"] for r in rows]


async def test_mute_excludes_overlapping_segments_per_channel(tmp_path: Path):
    """mic と system それぞれのミュート窓と重なるセグメントだけが除外される。"""
    conn = _conn()
    vs = FakeVectorStore()
    # mic 窓 3500-5500 が mic セグメント 4000-5000 を覆う。
    # system 窓 5500-7500 が system セグメント 6000-7000 を覆う。
    # offset 0(WAV 基準が t0 と一致)。
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "wav_start_offset_ms": 0,
                "mic": [{"start_ms": 3500, "end_ms": 5500}],
                "system": [{"start_ms": 5500, "end_ms": 7500}],
            }
        ),
        encoding="utf-8",
    )
    await _run(conn, vs, tmp_path / "mic.wav", tmp_path / "system.wav")

    texts = _chunk_texts(conn)
    joined = "\n".join(texts)
    # 窓外は残る
    assert "おはようございます" in joined
    assert "システムの通常発言" in joined
    # 窓と重なるものは除外
    assert "マイクのミュート対象" not in joined
    assert "システムのミュート対象" not in joined
    # ベクトルにも到達していない
    vtexts = {v.speaker for v in vs.upserts}  # noqa: F841 (just ensure no crash)
    assert vs.upserts, "no vectors upserted"
    assert len(vs.upserts) == len(texts)


async def test_mute_only_affects_its_own_channel(tmp_path: Path):
    """mic のミュート窓は system セグメントを落とさない(チャンネル独立)。"""
    conn = _conn()
    vs = FakeVectorStore()
    # mic 窓だけ。system 窓は空。mic 窓 0-3000 は mic 0-1000 を覆う。
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "wav_start_offset_ms": 0,
                "mic": [{"start_ms": 0, "end_ms": 3000}],
                "system": [],
            }
        ),
        encoding="utf-8",
    )
    await _run(conn, vs, tmp_path / "mic.wav", tmp_path / "system.wav")

    joined = "\n".join(_chunk_texts(conn))
    assert "おはようございます" not in joined  # mic 窓内 -> 除外
    assert "マイクのミュート対象" in joined     # mic 窓外 -> 残る
    # system はミュート窓なし -> 全て残る
    assert "システムの通常発言" in joined
    assert "システムのミュート対象" in joined


async def test_mute_offset_subtraction_applied(tmp_path: Path):
    """wav_start_offset_ms を減算した WAV 相対窓で判定される。"""
    conn = _conn()
    vs = FakeVectorStore()
    # offset 1000。t0 相対 mic 窓 5000-6000 -> WAV 相対 4000-5000 が mic 4000-5000 を覆う。
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "wav_start_offset_ms": 1000,
                "mic": [{"start_ms": 5000, "end_ms": 6000}],
                "system": [],
            }
        ),
        encoding="utf-8",
    )
    await _run(conn, vs, tmp_path / "mic.wav", tmp_path / "system.wav")

    joined = "\n".join(_chunk_texts(conn))
    assert "マイクのミュート対象" not in joined  # WAV 相対窓 4000-5000 と重なる -> 除外
    assert "おはようございます" in joined         # 窓外 -> 残る


async def test_no_mute_json_keeps_all_segments(tmp_path: Path):
    """mute_intervals.json が無い古い録音は従来どおり全セグメント保持(後方互換)。"""
    conn = _conn()
    vs = FakeVectorStore()
    # JSON を書かない
    await _run(conn, vs, tmp_path / "mic.wav", tmp_path / "system.wav")

    joined = "\n".join(_chunk_texts(conn))
    assert "おはようございます" in joined
    assert "マイクのミュート対象" in joined
    assert "システムの通常発言" in joined
    assert "システムのミュート対象" in joined
    status = conn.execute("SELECT status FROM sources WHERE id='src'").fetchone()["status"]
    assert status == "ready"


async def test_empty_mute_intervals_keeps_all(tmp_path: Path):
    """全チャンネル空区間の JSON でも何も除外しない。"""
    conn = _conn()
    vs = FakeVectorStore()
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps(
            {"version": 1, "wav_start_offset_ms": 0, "mic": [], "system": []}
        ),
        encoding="utf-8",
    )
    await _run(conn, vs, tmp_path / "mic.wav", tmp_path / "system.wav")
    joined = "\n".join(_chunk_texts(conn))
    assert "おはようございます" in joined
    assert "マイクのミュート対象" in joined
    assert "システムの通常発言" in joined
    assert "システムのミュート対象" in joined
