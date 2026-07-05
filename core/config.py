from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.crash_reporter.settings import CrashReportSettings


class OllamaSettings(BaseModel):
    endpoint: str = "http://localhost:11434"
    default_model: str = "qwen2.5:14b"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    # GPT-OSS:20B など大型モデルは初回ロードに 120 秒以上かかるため、
    # 既定を 600 秒(10 分)に伸ばす。VRAM が小さい GPU での CPU/GPU 分割ロードや
    # cold start を許容するための保険値。settings UI から個別調整も可能。
    request_timeout_seconds: float = 600.0
    # chat_stream の read タイムアウト(秒)。connect は httpx 既定のまま。
    # 詰まった Ollama が無限ハングせず例外→error イベントで表面化させる。
    # 大型モデルの first-token までの待ち時間も同じ理由で 600 秒に伸ばす。
    chat_read_timeout_seconds: float = 600.0
    # Workaround for llama.cpp GPU bug that emits NaN embeddings for some
    # multilingual inputs (esp. Japanese) under bge-m3. num_gpu=0 forces CPU
    # inference for embeddings. Set to None or {} to use Ollama defaults.
    embedding_options: dict[str, int] = Field(default_factory=lambda: {"num_gpu": 0})
    # Acceleration backend selection (Phase 1: CUDA-only baseline).
    # "auto" -> BackendPlanner picks "ollama-cuda" on RTX 2080 Ti, preserving
    # existing behavior. Phase 2 will widen the Literal to include
    # ipex-llm-ollama / ollama-vulkan / openvino-genai-server.
    runtime_backend: Literal["auto", "ollama-cuda"] = "auto"
    # Phase 2 will widen to include ollama-bge-m3-gpu / openvino-bge-m3-{igpu,npu}.
    text_embed_backend: Literal["auto", "ollama-bge-m3-cpu"] = "auto"


class GenerationSettings(BaseModel):
    context_budget_ratio: float = 0.8
    # 応答の num_predict 上限。思考モデル(qwen3 等)は thinking トークンも
    # ここを消費するため、1024 では議事録等の長出力が途中で切れる(2026-07-05 実機FB)。
    response_budget_tokens: int = 2048


class RetrievalSettings(BaseModel):
    top_k: int = 8
    top_k_max: int = 20
    min_history_turns: int = 1


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class McpSettings(BaseModel):
    enabled: bool = True


class AudioSettings(BaseModel):
    whisper_model: str = "large-v3"
    device: str = "cuda"            # cuda | cpu
    compute_type: str = "float16"   # float16 | int8_float16 | int8
    language: str = "ja"
    sample_rate: int = 16000
    mic_device_index: int | None = None
    system_device_index: int | None = None
    live_caption_default: bool = True
    agc_enabled: bool = True
    manual_boost_max_db: float = 18.0
    diarization_enabled: bool = True
    max_speakers: int | None = None     # None = auto
    # None -> <data_dir>/models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
    diarizer_segmentation_model: str | None = None
    # None -> <data_dir>/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
    diarizer_embedding_model: str | None = None
    diarizer_threshold: float = 0.5
    voiceprint_naming: bool = True
    name_inference_llm: bool = True
    name_threshold: float = 0.65
    storage_format: str = "aac"         # aac | opus | mp3 | wav
    storage_bitrate_kbps: int = 64
    keep_audio: bool = True
    auto_title: bool = True             # 停止後パイプラインで LLM がタイトル自動命名
    # Acceleration backend selection (Phase 1: CUDA-only baseline).
    # "auto" -> BackendPlanner picks faster-whisper-cuda / sherpa-onnx-cpu /
    # sherpa-onnx-cpu on RTX 2080 Ti, preserving existing behavior.
    # Phase 2 will widen the Literal to include openvino-whisper-{igpu,npu}.
    transcriber_backend: Literal[
        "auto", "faster-whisper-cuda", "faster-whisper-cpu"
    ] = "auto"
    diarizer_backend: Literal["auto", "sherpa-onnx-cpu"] = "auto"
    speaker_embed_backend: Literal["auto", "sherpa-onnx-cpu"] = "auto"


def _default_data_dir() -> Path:
    return Path.home() / ".notebook-ollama"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTEBOOK_OLLAMA_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    data_dir: Path = Field(default_factory=_default_data_dir)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    crash_report: CrashReportSettings = Field(default_factory=CrashReportSettings)

    @property
    def metadata_db_path(self) -> Path:
        return self.data_dir / "metadata.db"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def mcp_token_path(self) -> Path:
        return self.data_dir / "mcp.token"

    # ------------------------------------------------------------------
    # Crash-report / Feedback Hub paths (spec §4 / §7.2, plan Sprint 3)
    # ------------------------------------------------------------------
    @property
    def crash_pending_dir(self) -> Path:
        """未送信 crash レポート (PendingCrash JSON) のディレクトリ。"""
        return self.data_dir / "crash-pending"

    @property
    def reported_path(self) -> Path:
        """既報 fingerprint を 1 行 1 ハッシュで永続化するファイル。"""
        return self.data_dir / "reported.txt"

    @property
    def running_lock_path(self) -> Path:
        """uvicorn プロセス PID を保持する lock。unclean shutdown 検知に使う。"""
        return self.data_dir / "running.lock"

    @property
    def notices_path(self) -> Path:
        """お知らせ (FeedbackHub Notice タブ) の app-bundled JSON 配置。

        ユーザの ``data_dir`` ではなくリポジトリ同梱の ``<repo>/data/notices.json``
        を返す (plan Task 3.6 / 3.7: お知らせはアプリ配布物の一部)。
        """
        # core/config.py → parents[1] = <repo root>
        return Path(__file__).resolve().parents[1] / "data" / "notices.json"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.qdrant_path,
            self.sources_dir,
            self.logs_dir,
            self.crash_pending_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)
