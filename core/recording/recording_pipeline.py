"""録音オフライン取り込みパイプライン (純粋オーケストレーション)。

完了した録音の 2 つの wav (mic / system) から、タイムコード + 話者付きの RAG
チャンクを生成して埋め込み、SSE 進捗ステップを発行する。

処理順:
  STT → diarization(system) → LLM 名前推定 → セグメント整列校正 → チャンク化 →
  埋め込み → status READY

依存 (transcriber / diarizer / ollama / broker / vector_store) は全て注入されるため、
実モデル・実音声なしで fake を渡して完全にユニットテストできる。アプリ層への配線と
声紋ベースの命名は別タスク。ここでは行わない。

IngestionPipeline (core/ingestion/pipeline.py) の埋め込みループ・broker.publish・
try/except エラーハンドリングのパターンをミラーしている。
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.ids import new_id
from core.logging import get_logger
from core.recording.audio_export import convert_audio, delete_if_exists, ext_for_format
from core.recording.chunking import chunk_segments
from core.recording.merger import merge
from core.recording.name_inference import infer_names
from core.recording.segment_correct import Segment, correct_segments_aligned
from core.recording.title_inference import infer_title
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.sources_repo import (
    SourceStatus,
    update_source_status,
    update_source_title,
)
from core.storage.vector_store import ChunkVector

log = get_logger("recording.pipeline")

_MIC_SPEAKER = "あなた"
_SYSTEM_SPEAKER = "相手"
_MIC_CHANNEL = "mic"
_SYSTEM_CHANNEL = "system"

_CANCELLED_MSG = "変換を停止しました"


class ConversionCancelled(Exception):
    """ユーザーがオフライン変換の停止を要求したことを表す内部シグナル。

    run() はステップ境界 / 埋め込みループでこれを送出し、except で status=error に
    落として握りつぶす(background task なので再送出しない)。"""


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...
    async def generate(self, *, model: str, prompt: str, options: Any = ...) -> str: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


class _VectorStoreLike(Protocol):
    def upsert(self, vectors: Any) -> None: ...


class _TranscriberLike(Protocol):
    def transcribe(
        self, wav_path: Path, *, channel: str, speaker_id: str,
        language: str = ..., session_id: str = ...,
    ) -> list[Any]: ...


class _DiarizerLike(Protocol):
    def diarize(self, wav_path: Path) -> list[Any]: ...


@dataclass
class RecordingPipelineDeps:
    conn: sqlite3.Connection
    vector_store: _VectorStoreLike
    ollama: _GatewayLike
    embedding_model: str
    broker: _BrokerLike | None = None
    embedding_model_getter: Callable[[], str] | None = None
    # READY 直後に呼ばれる要約フック。失敗しても録音取込は READY を維持する。
    summary_runner: Callable[[str], Any] | None = None


def _token_counter(text: str) -> int:
    """チャンク化用トークン数。core.tokens があれば使い、無ければ空白語数。"""
    try:
        from core.tokens import count_tokens
        return count_tokens(text)
    except Exception:
        return len(text.split())


class RecordingPipeline:
    def __init__(self, *, deps: RecordingPipelineDeps) -> None:
        self._deps = deps
        # 進行中変換の協調キャンセル用。endpoint が request_cancel で source_id を
        # 積み、run がステップ境界で is_cancelled を見て中断する。run/endpoint は同一
        # イベントループだが、将来 STT 等をスレッドに退避しても安全なよう lock を持つ。
        self._cancelled: set[str] = set()
        self._cancel_lock = threading.Lock()

    def request_cancel(self, source_id: str) -> None:
        """進行中の変換に停止を要求する(次のチェックポイントで中断)。"""
        with self._cancel_lock:
            self._cancelled.add(source_id)

    def is_cancelled(self, source_id: str) -> bool:
        with self._cancel_lock:
            return source_id in self._cancelled

    def _clear_cancel(self, source_id: str) -> None:
        with self._cancel_lock:
            self._cancelled.discard(source_id)

    def _check_cancel(self, source_id: str) -> None:
        if self.is_cancelled(source_id):
            raise ConversionCancelled

    def _embedding_model(self) -> str:
        getter = self._deps.embedding_model_getter
        return getter() if getter is not None else self._deps.embedding_model

    async def _publish(
        self, *, notebook_id: str, source_id: str, step: str, label: str,
        progress: float, status: str,
    ) -> None:
        if self._deps.broker is None:
            return
        await self._deps.broker.publish(
            f"notebook:{notebook_id}",
            {
                "source_id": source_id,
                "step": step,
                "step_label": label,
                "progress": progress,
                "status": status,
            },
        )

    async def run(
        self,
        *,
        source_id: str,
        notebook_id: str,
        mic_wav: Path | None,
        system_wav: Path | None,
        transcriber: _TranscriberLike,
        diarizer: _DiarizerLike,
        model: str,
        diarization_enabled: bool,
        name_inference_enabled: bool,
        name_threshold: float,
        max_tokens: int = 400,
        storage_format: str = "aac",
        storage_bitrate_kbps: int = 64,
        keep_audio: bool = True,
        auto_title_enabled: bool = True,
    ) -> None:
        conn = self._deps.conn
        # 話者ラベル (rename 後も含む) → channel のマップ。チャンクの channel 決定に使う。
        speaker_channel: dict[str, str] = {}

        try:
            self._check_cancel(source_id)
            update_source_status(conn, source_id, status=SourceStatus.PARSING)

            # --- 1. transcribe -------------------------------------------------
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="transcribe",
                label="文字起こし中", progress=0.1, status=SourceStatus.PARSING.value,
            )
            mic_segments: list[Segment] = []
            system_transcripts: list[Any] = []

            if mic_wav is not None:
                # CPU/GPUバウンドの同期STTはワーカースレッドへオフロードし、
                # イベントループを塞がない(issue #11: 変換中に全API無応答)。
                mic_raw = await asyncio.to_thread(
                    transcriber.transcribe,
                    mic_wav, channel=_MIC_CHANNEL, speaker_id=_MIC_SPEAKER,
                    session_id=source_id,
                )
                for ts in mic_raw:
                    mic_segments.append(Segment(
                        start_ms=ts.start_ms, end_ms=ts.end_ms,
                        speaker=_MIC_SPEAKER, text=ts.text,
                        language=ts.language or "ja",
                    ))
                speaker_channel[_MIC_SPEAKER] = _MIC_CHANNEL

            if system_wav is not None:
                system_transcripts = await asyncio.to_thread(
                    transcriber.transcribe,
                    system_wav, channel=_SYSTEM_CHANNEL, speaker_id=_SYSTEM_SPEAKER,
                    session_id=source_id,
                )

            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="transcribe",
                label="文字起こし完了", progress=0.25, status=SourceStatus.PARSING.value,
            )
            self._check_cancel(source_id)

            # --- 2. diarize (system のみ) -------------------------------------
            system_segments: list[Segment] = []
            if system_transcripts:
                if diarization_enabled:
                    await self._publish(
                        notebook_id=notebook_id, source_id=source_id, step="diarize",
                        label="話者分離中", progress=0.35,
                        status=SourceStatus.PARSING.value,
                    )
                    diar = await asyncio.to_thread(diarizer.diarize, system_wav)
                    merged = merge(system_transcripts, diar)
                    # merge() は spk_NNN / spk_unknown を speaker_id に割り当てる。
                    # 出現順で 相手1, 相手2, ... に決定論的にマップする。
                    label_map: dict[str, str] = {}
                    for ts in merged:
                        spk = ts.speaker_id
                        if spk not in label_map:
                            label_map[spk] = f"{_SYSTEM_SPEAKER}{len(label_map) + 1}"
                        name = label_map[spk]
                        speaker_channel[name] = _SYSTEM_CHANNEL
                        system_segments.append(Segment(
                            start_ms=ts.start_ms, end_ms=ts.end_ms,
                            speaker=name, text=ts.text, language=ts.language or "ja",
                        ))
                    await self._publish(
                        notebook_id=notebook_id, source_id=source_id, step="diarize",
                        label="話者分離完了", progress=0.45,
                        status=SourceStatus.PARSING.value,
                    )
                else:
                    # diarization 無効: 全て単一話者 '相手'。
                    speaker_channel[_SYSTEM_SPEAKER] = _SYSTEM_CHANNEL
                    for ts in system_transcripts:
                        system_segments.append(Segment(
                            start_ms=ts.start_ms, end_ms=ts.end_ms,
                            speaker=_SYSTEM_SPEAKER, text=ts.text,
                            language=ts.language or "ja",
                        ))

            # ミュート区間の除外は不要: recorder が録音時にミュート中チャンネルの WAV を
            # 無音化しているため、STT がミュート区間から何も生成しない(無音 → VAD 除去)。
            # よってここに到達するセグメントには既にミュート発話が含まれない。

            all_segments: list[Segment] = sorted(
                mic_segments + system_segments, key=lambda s: s.start_ms
            )

            # --- 3. name inference --------------------------------------------
            if name_inference_enabled and all_segments:
                await self._publish(
                    notebook_id=notebook_id, source_id=source_id, step="name_infer",
                    label="話者名推定中", progress=0.5,
                    status=SourceStatus.PARSING.value,
                )
                names = await infer_names(
                    [{"speaker": s.speaker, "text": s.text} for s in all_segments],
                    self._deps.ollama, model, threshold=name_threshold,
                )
                if names:
                    renamed: list[Segment] = []
                    for s in all_segments:
                        new_name = names.get(s.speaker)
                        if new_name and new_name != s.speaker:
                            # rename しても channel は元話者のものを引き継ぐ。
                            speaker_channel[new_name] = speaker_channel.get(
                                s.speaker, _SYSTEM_CHANNEL
                            )
                            renamed.append(Segment(
                                start_ms=s.start_ms, end_ms=s.end_ms,
                                speaker=new_name, text=s.text, language=s.language,
                            ))
                        else:
                            renamed.append(s)
                    all_segments = renamed

            # --- 4. correct ----------------------------------------------------
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="correct",
                label="校正中", progress=0.6, status=SourceStatus.PARSING.value,
            )
            corrected = await correct_segments_aligned(
                all_segments, self._deps.ollama, model
            )

            # --- 4.5 自動タイトル命名 (best-effort, READY を阻害しない) ----------
            # 整文済みトランスクリプトから LLM で簡潔なタイトルを 1 つ予想し、
            # source.title に設定する。失敗・空でもパイプラインは継続する。
            if auto_title_enabled and corrected:
                try:
                    title = await infer_title(
                        [{"speaker": s.speaker, "text": s.text} for s in corrected],
                        self._deps.ollama, model,
                    )
                    if title:
                        update_source_title(conn, source_id, title)
                except Exception:
                    log.warning("recording_auto_title_failed", source_id=source_id)

            # --- 5. chunk ------------------------------------------------------
            self._check_cancel(source_id)
            update_source_status(conn, source_id, status=SourceStatus.CHUNKING)
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="chunk",
                label="チャンク化中", progress=0.7, status=SourceStatus.CHUNKING.value,
            )
            chunks = chunk_segments(
                corrected, max_tokens=max_tokens, token_counter=_token_counter
            )

            # --- 6. embed + store ---------------------------------------------
            total = len(chunks)
            update_source_status(
                conn, source_id, status=SourceStatus.EMBEDDING, chunk_count=total
            )
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="embed",
                label="埋め込み中", progress=0.8, status=SourceStatus.EMBEDDING.value,
            )

            records: list[ChunkRecord] = []
            vectors: list[ChunkVector] = []
            for chunk in chunks:
                self._check_cancel(source_id)
                vec = await self._deps.ollama.embed(
                    model=self._embedding_model(), text=chunk.text
                )
                # チャンク内のセグメントは同一話者 (chunking が話者で分割) なので
                # channel も一意。rename 後の話者ラベルから channel を引く。
                channel = speaker_channel.get(chunk.speaker, _SYSTEM_CHANNEL)
                chunk_id = new_id()
                records.append(ChunkRecord(
                    id=chunk_id, source_id=source_id, notebook_id=notebook_id,
                    ord=chunk.ord, page=None, heading_path=None, text=chunk.text,
                    token_count=chunk.token_count, start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms, speaker=chunk.speaker,
                ))
                vectors.append(ChunkVector(
                    id=chunk_id, vector=vec, notebook_id=notebook_id,
                    source_id=source_id, source_kind="recording", page=None,
                    heading_path=None, ord=chunk.ord, start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms, speaker=chunk.speaker, channel=channel,
                ))

            self._check_cancel(source_id)
            if records:
                insert_chunks(conn, records)
            if vectors:
                self._deps.vector_store.upsert(vectors)

            # --- 6.5 音声圧縮 (best-effort, READY 前) ---------------------------
            # 圧縮失敗は致命的でない: チャンクは埋め込み済みで RAG は成立している。
            # 失敗したチャンネルは WAV を残し、再生はその WAV で継続できる。
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="compress",
                label="音声圧縮中", progress=0.9, status=SourceStatus.EMBEDDING.value,
            )
            ext = ext_for_format(storage_format)
            for wav in (mic_wav, system_wav):
                if wav is None or not wav.exists():
                    continue
                if not keep_audio:
                    delete_if_exists(wav)
                    continue
                if storage_format == "wav":
                    continue  # 生 WAV をそのまま保存形式とする
                try:
                    dst = wav.with_suffix(ext)
                    await convert_audio(
                        wav, dst, fmt=storage_format,
                        bitrate_kbps=storage_bitrate_kbps,
                    )
                    delete_if_exists(wav)  # 変換成功後にのみ WAV 削除
                except Exception:
                    log.warning(
                        "recording_compress_failed",
                        source_id=source_id, channel=wav.stem,
                    )

            # --- 7. status READY ----------------------------------------------
            update_source_status(
                conn, source_id, status=SourceStatus.READY, chunk_count=total
            )
            await self._publish(
                notebook_id=notebook_id, source_id=source_id, step="done",
                label="完了", progress=1.0, status=SourceStatus.READY.value,
            )
            log.info(
                "recording_ingestion_complete",
                source_id=source_id, chunk_count=total,
            )

            # Best-effort: 要約フック(失敗しても READY は維持する)。
            if self._deps.summary_runner is not None:
                try:
                    result = self._deps.summary_runner(source_id)
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    log.warning(
                        "recording_summary_runner_failed", source_id=source_id
                    )

        except ConversionCancelled:
            # ユーザー停止: error("...停止...") に落として握りつぶす(再送出しない)。
            update_source_status(
                conn, source_id, status=SourceStatus.ERROR, error_msg=_CANCELLED_MSG
            )
            # SSE publish 失敗で background task をクラッシュさせない (DB 側の
            # status は既に更新済み)。
            with contextlib.suppress(Exception):
                await self._publish(
                    notebook_id=notebook_id, source_id=source_id, step="error",
                    label="停止しました", progress=1.0, status=SourceStatus.ERROR.value,
                )
            log.info("recording_ingestion_cancelled", source_id=source_id)
        except Exception as exc:  # background task: 例外は status に記録して握りつぶす
            update_source_status(
                conn, source_id, status=SourceStatus.ERROR, error_msg=str(exc)
            )
            # SSE publish 失敗で background task をクラッシュさせない (DB 側の
            # status は既に更新済み)。
            with contextlib.suppress(Exception):
                await self._publish(
                    notebook_id=notebook_id, source_id=source_id, step="error",
                    label="エラー", progress=1.0, status=SourceStatus.ERROR.value,
                )
            log.exception("recording_ingestion_failed", source_id=source_id)
        finally:
            # 成否に関わらず停止フラグをクリアし、後続の再試行が事前キャンセル状態に
            # ならないようにする。
            self._clear_cancel(source_id)
