from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.crash_reporter.settings import CrashReportSettings
from core.visual.units import DEFAULT_VISUAL_UNIT, VisualUnit


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
    # Acceleration backend selection (Phase 1.5 — spec addendum 2026-08-02).
    # "auto" -> BackendPlanner picks "ollama-cuda" on RTX 2080 Ti, preserving
    # existing behavior. "ollama-vulkan" is the official Ollama with its
    # Vulkan backend (Intel/AMD iGPU); "openai-compat" points the gateway at
    # openai_compat_endpoint (llama-server / OVMS / Lemonade / LM Studio 等)。
    # ipex-llm-ollama は addendum K2(security issues)で不採用。
    runtime_backend: Literal[
        "auto", "ollama-cuda", "ollama-vulkan", "openai-compat"
    ] = "auto"
    # "openai-compat-embed" -> /v1/embeddings at openai_compat_embed_endpoint
    # (未設定なら openai_compat_endpoint)。生成と埋め込みを別サーバーに
    # 分離できる(addendum M: 非対称構成)。Phase 2 で openvino-bge-m3-{igpu,npu}。
    text_embed_backend: Literal[
        "auto", "ollama-bge-m3-cpu", "openai-compat-embed"
    ] = "auto"
    # OpenAI互換サーバーのベース URL(例 "http://localhost:8080")。
    # runtime_backend="openai-compat" のとき必須。空 = 未設定。
    openai_compat_endpoint: str = ""
    # 埋め込み専用の OpenAI互換サーバー URL。空なら openai_compat_endpoint を
    # 流用する(addendum M: 生成=NPU/iGPU・埋め込み=iGPU/CPU の非対称構成用)。
    openai_compat_embed_endpoint: str = ""
    # llama-server --api-key 等での運用時のみ設定。空ならヘッダを送らない。
    openai_compat_api_key: str = ""
    # 視覚モデル(Stage 2)。空文字列 = 未設定(describe段・OCR経路はスキップ)。
    vision_model: str = ""
    # 取込時に図を自動でVLM解析するか(既定ON)。OFFでも「図を解析」で手動実行可能。
    auto_describe_figures: bool = True


class DevModeSettings(BaseModel):
    """開発者モード(spec: docs/specs/2026-07-02-developer-mode-design.md)。

    enabled は既定 OFF。ON でも Dev API は localhost 限定(§5.2)。
    log_capacity_bytes は 1MB..200MB にクランプして採用する(§9.2 E7)。
    """

    enabled: bool = False
    log_capacity_bytes: int = 20 * 1024 * 1024


class GenerationSettings(BaseModel):
    context_budget_ratio: float = 0.8
    # 応答の num_predict 上限。思考モデル(qwen3 等)は thinking トークンも
    # ここを消費するため、1024 では議事録等の長出力が途中で切れる(2026-07-05 実機FB)。
    response_budget_tokens: int = 2048
    # done_reason=length 検知時に assistant prefill で自動継続する最大回数。
    # 0 で無効(打ち切り注記のみ)。上限5は num_ctx 押し出しの安全弁(issue #22)。
    auto_continue_max: int = 2


class RetrievalSettings(BaseModel):
    top_k: int = 8
    top_k_max: int = 20
    min_history_turns: int = 1


class VisualSettings(BaseModel):
    """視覚埋め込み第2インデックス (Stage 3, 実験枠)。"""

    # HuggingFace モデルID。実在IDは実機ゲートで検証し、必要なら設定で差し替える
    embedding_model: str = "Qwen/Qwen3-VL-Embedding-2B"
    # 「視覚検索を使う」トグル(既定ON。実行にはベータON+構築済み+extra導入も必要)
    search_enabled: bool = True
    # アイドルアンロード秒数(spec §7: 11GB VRAMでチャットLLMと共存するため)
    idle_unload_seconds: float = 300.0
    # ページレンダリングDPI(spec §11: 埋め込みは高DPI不要)
    render_dpi: int = 100
    # 構築時のページ間クールダウン秒。CPU埋め込みは全コアAVX全開が1ページ
    # 数十秒続く実質ストレステストで、連続実行はマシンの電源/熱マージンを
    # 削る(実機で長時間構築中にBSOD 0x7F_8を観測)。バースト間に休止を挟み
    # デューティ比を下げる。0で無効。
    # 既定10秒: 全力プロファイル(休止2秒+全スレッド)は実機50ページ構築で
    # BSOD 2回、この安全プロファイルは50ページ完走(約95秒/ページ、RSS一定)。
    build_cooldown_seconds: float = 10.0
    # CPU推論の torch スレッド数上限。0 = torch既定(全論理コア)。
    # 既定4: 全論理コア(24)ではCPU電力ピークがマシンの安定性マージンを超えた
    # (上記BSOD)。P-core優先(下記)と併せた「少数P-core分業」プロファイル —
    # E-coreクラスタを空けてブラウザ等の背景処理との競合を避ける。
    # 速度優先なら設定で引き上げ可(自己責任)。
    cpu_threads: int = 4
    # Windows のハイブリッドCPU(P+E core)でP-coreに載せるか。バックグラウンド
    # プロセスは EcoQoS で E-core に寄せられ、8スレッドがE-core 8基を100%飽和
    # →ブラウザ背景処理と競合してカクつく(実機観測 2026-07-26)。True なら
    # 推論バックエンド常駐中だけ EcoQoS を解除し、少数の重スレッドを
    # P-core へ載せる(fork-join並列はP/E混載だと遅いE側が律速になるため、
    # 均等分配ではなくクラスタ分業が正解)。Windows以外では無効。
    cpu_prefer_performance_cores: bool = True
    # --- Stage 4: PixelRAG式タイル索引と検索戦略の選択 ---
    # 検索に使う視覚索引の単位。"page" = 現行(1ページ1ベクトル)、
    # "tile" = PixelRAG式(ページをタイル分割して各タイルを1ベクトル)。
    # 両方の索引を同時保持できるため、切替に再構築は不要。
    index_unit: VisualUnit = DEFAULT_VISUAL_UNIT
    # 検索戦略。
    #   hybrid_rrf   = テキスト検索 + 視覚検索を RRF 融合(現行・既定)
    #   visual_only  = 視覚検索のみで候補を決め、本文は従来どおりページ展開
    #   pixel_native = 視覚検索のみ。本文は載せず画像だけを VLM に渡す
    search_strategy: Literal["hybrid_rrf", "visual_only", "pixel_native"] = "hybrid_rrf"
    # タイル分割の格子。既定は縦3分割・列分割なし(A4縦の技術文書は情報が
    # 縦方向に積層するため行分割が効く。2段組資料は tile_cols で対応)。
    tile_rows: int = 3
    tile_cols: int = 1
    # 隣接タイルの重なり率(基準辺長に対する比)。分割線が表や図を横切った
    # ときに両側のタイルへ手掛かりを残すマージン。0 だと境界上の要素が
    # どちらのタイルからも読み取れなくなる。
    tile_overlap: float = 0.1
    # pixel_native 戦略で VLM に渡す画像の最大枚数。他の戦略では現行どおり
    # 2枚上限。タイルはページ全体より小さくトークン消費が少ないため多く積める。
    max_images: int = 4


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


class VoiceInputSettings(BaseModel):
    """チャット音声入力(spec 2026-07-05-chat-voice-input-design §5)。

    - mode: off / push_to_talk(既定) / hands_free
    - ptt_key: KeyboardEvent.code の単一キー文字列(既定 "Space")
    """
    mode: Literal["off", "push_to_talk", "hands_free"] = "push_to_talk"
    ptt_key: str = "Space"


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
    visual: VisualSettings = Field(default_factory=VisualSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    crash_report: CrashReportSettings = Field(default_factory=CrashReportSettings)
    voice_input: VoiceInputSettings = Field(default_factory=VoiceInputSettings)
    dev: DevModeSettings = Field(default_factory=DevModeSettings)

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
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

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
