from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class GenerationSettings(BaseModel):
    context_budget_ratio: float = 0.8
    response_budget_tokens: int = 1024


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
    diarizer_segmentation_model: str | None = None  # None -> <data_dir>/models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
    diarizer_embedding_model: str | None = None      # None -> <data_dir>/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
    diarizer_threshold: float = 0.5
    voiceprint_naming: bool = True
    name_inference_llm: bool = True
    name_threshold: float = 0.65
    storage_format: str = "aac"         # aac | opus | mp3 | wav
    storage_bitrate_kbps: int = 64
    keep_audio: bool = True
    auto_title: bool = True             # 停止後パイプラインで LLM がタイトル自動命名


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

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.qdrant_path, self.sources_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)
