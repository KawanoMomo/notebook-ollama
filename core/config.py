from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaSettings(BaseModel):
    endpoint: str = "http://localhost:11434"
    default_model: str = "qwen2.5:14b"
    embedding_model: str = "bge-m3"
    request_timeout_seconds: float = 120.0
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
    voiceprint_naming: bool = True
    name_inference_llm: bool = True
    name_threshold: float = 0.65
    storage_format: str = "aac"         # aac | opus | mp3 | wav
    storage_bitrate_kbps: int = 64
    keep_audio: bool = True


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
