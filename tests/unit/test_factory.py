"""Sprint 3 / Task 3.2 — ``BackendFactory`` Phase 1 CUDA-only builders.

Coverage:

* ``build_transcriber`` for ``faster-whisper-cuda`` / ``faster-whisper-cpu``
  routes to the existing ``Transcriber`` class with the correct
  ``device`` / ``compute_type``.
* ``build_transcriber`` raises ``NotImplementedError("Phase 2 ...")`` for
  every Phase 2 STT id (``openvino-whisper-igpu`` / ``openvino-whisper-npu`` /
  ``amd-whispercpp-dml``).
* ``build_diarizer`` for ``sherpa-onnx-cpu`` constructs the existing
  ``SherpaDiarizer`` with the audio-config-resolved model paths.
* ``build_llm_gateway`` for ``ollama-cuda`` constructs an ``OllamaGateway``
  with an ``OllamaClient`` pinned to ``ollama_cfg.endpoint``.
* ``build_llm_gateway`` raises ``NotImplementedError("Phase 2 ...")`` for
  every Phase 2 LLM id (``ollama-directml`` / ``ipex-llm-ollama``).
* ``build_text_embedder`` for ``ollama-bge-m3-cpu`` returns a wrapper bound
  to ``ollama_cfg.embedding_model`` and forwards ``embed(text)`` to the
  underlying gateway with the right model name.

Heavy resources (faster_whisper ``WhisperModel`` load, sherpa_onnx
``OfflineSpeakerDiarization`` construction) are mocked via
``monkeypatch.setitem(sys.modules, ...)`` so the tests run on any host
without GPU/CUDA/ONNX runtimes installed.

INVARIANT (mirrored from ``core/accel/factory.py``): the Factory must not
modify any constructor signature of the existing concrete classes. The
tests assert ``isinstance(result, Transcriber)`` / ``SherpaDiarizer`` /
``OllamaGateway`` directly so a future signature drift would surface here
as well as in the legacy DI tests.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.accel.factory import BackendFactory, _OllamaTextEmbedder
from core.accel.plan import BackendPlan
from core.accel.profile import HwProfile
from core.config import AudioSettings, OllamaSettings
from core.ollama.gateway import OllamaGateway

# ---------------------------------------------------------------------------
# HwProfile / BackendPlan fixtures
# ---------------------------------------------------------------------------


_CUDA_PROFILE: HwProfile = HwProfile(
    vendor="nvidia",
    cpu_brand="12th Gen Intel(R) Core(TM) i9-12900KF",
    dgpu="NVIDIA GeForce RTX 2080 Ti",
    igpu=None,
    npu=None,
    vram_mb=11264,
    ryzen_ai_gen=None,
    openvino_devices=(),
    has_directml=False,
    has_cuda=True,
    cuda_device_count=1,
)

_CPU_PROFILE: HwProfile = HwProfile(
    vendor="unknown",
    cpu_brand="generic-cpu",
    dgpu=None,
    igpu=None,
    npu=None,
    vram_mb=None,
    ryzen_ai_gen=None,
    openvino_devices=(),
    has_directml=False,
    has_cuda=False,
    cuda_device_count=0,
)


def _cuda_plan(**overrides: Any) -> BackendPlan:
    """Phase 1 CUDA plan — all four ids are Phase 1 implementable."""
    base = dict(
        stt_id="faster-whisper-cuda",
        diarize_id="sherpa-onnx-cpu",
        llm_id="ollama-cuda",
        text_embed_id="ollama-bge-m3-cpu",
        hw_profile=_CUDA_PROFILE,
        reason="RTX 2080 Ti detected -> faster-whisper-cuda",
    )
    base.update(overrides)
    return BackendPlan(**base)  # type: ignore[arg-type]


def _cpu_plan(**overrides: Any) -> BackendPlan:
    """All-CPU plan — used to exercise the CPU transcriber branch."""
    base = dict(
        stt_id="faster-whisper-cpu",
        diarize_id="sherpa-onnx-cpu",
        llm_id="ollama-cuda",
        text_embed_id="ollama-bge-m3-cpu",
        hw_profile=_CPU_PROFILE,
        reason="no GPU detected -> faster-whisper-cpu",
    )
    base.update(overrides)
    return BackendPlan(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Heavy-import mocks (faster_whisper, sherpa_onnx)
# ---------------------------------------------------------------------------


def _stub_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``faster_whisper`` in ``sys.modules`` with a MagicMock-backed stub.

    Returns the ``WhisperModel`` MagicMock so the test can assert on the
    constructor call (``model_size`` / ``device`` / ``compute_type``).
    """
    whisper_model_ctor = MagicMock(name="WhisperModel")
    whisper_model_ctor.return_value = MagicMock(name="WhisperModelInstance")
    fake = types.SimpleNamespace(WhisperModel=whisper_model_ctor)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    return whisper_model_ctor


def _stub_sherpa_onnx(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``sherpa_onnx`` in ``sys.modules`` with a MagicMock-backed stub.

    Returns the ``OfflineSpeakerDiarization`` MagicMock so the test can
    assert on the model-config wiring without loading any ONNX bytes.
    """
    diarization_ctor = MagicMock(name="OfflineSpeakerDiarization")
    diarization_ctor.return_value = MagicMock(name="OfflineSpeakerDiarizationInstance")
    fake = types.SimpleNamespace(
        OfflineSpeakerDiarization=diarization_ctor,
        OfflineSpeakerDiarizationConfig=MagicMock(name="OfflineSpeakerDiarizationConfig"),
        OfflineSpeakerSegmentationModelConfig=MagicMock(
            name="OfflineSpeakerSegmentationModelConfig"
        ),
        OfflineSpeakerSegmentationPyannoteModelConfig=MagicMock(
            name="OfflineSpeakerSegmentationPyannoteModelConfig"
        ),
        SpeakerEmbeddingExtractorConfig=MagicMock(
            name="SpeakerEmbeddingExtractorConfig"
        ),
        FastClusteringConfig=MagicMock(name="FastClusteringConfig"),
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    return diarization_ctor


# ---------------------------------------------------------------------------
# build_transcriber
# ---------------------------------------------------------------------------


def test_build_transcriber_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    """``faster-whisper-cuda`` → ``Transcriber(device='cuda', compute_type=cfg.*)``.

    The factory must pass ``audio_cfg.whisper_model`` and
    ``audio_cfg.compute_type`` through verbatim (no signature changes).
    """
    whisper_ctor = _stub_faster_whisper(monkeypatch)
    audio_cfg = AudioSettings(
        whisper_model="large-v3", device="cuda", compute_type="float16"
    )

    instance = BackendFactory().build_transcriber(_cuda_plan(), audio_cfg)

    # Import locally so the monkeypatched faster_whisper is the version
    # the factory sees on its lazy import.
    from core.recording.transcriber import Transcriber

    assert isinstance(instance, Transcriber)
    assert instance.effective_device == "cuda"
    whisper_ctor.assert_called_once_with(
        "large-v3", device="cuda", compute_type="float16"
    )


def test_build_transcriber_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """``faster-whisper-cpu`` → ``Transcriber(device='cpu', compute_type='int8')``.

    CPU compute_type is fixed to ``int8`` (float16 is not supported on CPU
    and the existing CPU fallback path also hard-codes ``int8``).
    """
    whisper_ctor = _stub_faster_whisper(monkeypatch)
    # audio_cfg still says cuda/float16 — the factory MUST override based
    # on the resolved stt_id, not on the raw audio_cfg.device field.
    audio_cfg = AudioSettings(
        whisper_model="large-v3", device="cuda", compute_type="float16"
    )

    instance = BackendFactory().build_transcriber(_cpu_plan(), audio_cfg)

    from core.recording.transcriber import Transcriber

    assert isinstance(instance, Transcriber)
    assert instance.effective_device == "cpu"
    whisper_ctor.assert_called_once_with("large-v3", device="cpu", compute_type="int8")


@pytest.mark.parametrize(
    "stt_id",
    [
        "openvino-whisper-igpu",
        "openvino-whisper-npu",
        "amd-whispercpp-dml",
    ],
)
def test_build_transcriber_phase2_raises(stt_id: str) -> None:
    """Every Phase 2 STT id raises ``NotImplementedError`` with /Phase 2/ AND id.

    The Factory contract (factory.py docstring + ``_phase2_not_implemented``)
    says the error message must include BOTH the substring ``"Phase 2"`` AND
    the requested id so operators can identify which backend was attempted
    without re-deriving it from the role / host context.
    """
    # Build a profile compatible with the Phase 2 id so BackendPlan
    # validation passes — the plan is *valid*, but not yet implementable.
    if stt_id == "amd-whispercpp-dml":
        profile = HwProfile(
            vendor="amd",
            cpu_brand="AMD Ryzen 9 8945HX",
            dgpu=None,
            igpu=None,
            npu="hawk_point",
            vram_mb=None,
            ryzen_ai_gen=1,
            openvino_devices=(),
            has_directml=True,
            has_cuda=False,
            cuda_device_count=0,
        )
    else:
        profile = HwProfile(
            vendor="intel",
            cpu_brand="Intel Core Ultra 7 155H",
            dgpu=None,
            igpu="Intel iGPU",
            npu="Intel NPU",
            vram_mb=None,
            ryzen_ai_gen=None,
            openvino_devices=("CPU", "GPU", "NPU"),
            has_directml=False,
            has_cuda=False,
            cuda_device_count=0,
        )

    plan = BackendPlan(
        stt_id=stt_id,
        diarize_id="sherpa-onnx-cpu",
        llm_id="ollama-cuda",
        text_embed_id="ollama-bge-m3-cpu",
        hw_profile=profile,
        reason=f"Phase 2 stt_id={stt_id} on {profile.vendor} host",
    )
    audio_cfg = AudioSettings()

    with pytest.raises(NotImplementedError) as exc_info:
        BackendFactory().build_transcriber(plan, audio_cfg)
    assert "Phase 2" in str(exc_info.value)
    assert stt_id in str(exc_info.value)


# ---------------------------------------------------------------------------
# build_diarizer
# ---------------------------------------------------------------------------


def test_build_diarizer_cpu_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``sherpa-onnx-cpu`` → existing ``SherpaDiarizer`` with resolved paths."""
    diarization_ctor = _stub_sherpa_onnx(monkeypatch)
    seg_path = tmp_path / "segmentation.onnx"
    emb_path = tmp_path / "embedding.onnx"
    # Touch the files so ``Path`` reads in the assertion would succeed —
    # the factory itself only stringifies them, but real-world usage opens
    # them so we keep the test realistic.
    seg_path.touch()
    emb_path.touch()

    audio_cfg = AudioSettings(
        diarizer_segmentation_model=str(seg_path),
        diarizer_embedding_model=str(emb_path),
        diarizer_threshold=0.5,
        max_speakers=None,
    )

    instance = BackendFactory().build_diarizer(_cuda_plan(), audio_cfg)

    from core.recording.diarizer import SherpaDiarizer

    assert isinstance(instance, SherpaDiarizer)
    # sherpa_onnx.OfflineSpeakerDiarization was called once (the actual
    # config object is the mock-built Config — we just assert construction
    # happened so the factory wiring is exercised end to end).
    assert diarization_ctor.call_count == 1


# ---------------------------------------------------------------------------
# build_llm_gateway
# ---------------------------------------------------------------------------


def test_build_llm_ollama_cuda() -> None:
    """``ollama-cuda`` → ``OllamaGateway`` whose client points at ``ollama_cfg.endpoint``."""
    ollama_cfg = OllamaSettings(
        endpoint="http://localhost:11434",
        request_timeout_seconds=99.0,
        chat_read_timeout_seconds=88.0,
    )

    gateway = BackendFactory().build_llm_gateway(_cuda_plan(), ollama_cfg)

    assert isinstance(gateway, OllamaGateway)
    # The wrapped client must carry the endpoint verbatim (the gateway
    # exposes it through the private ``_client`` attr — we read it for
    # the assertion only, not as a stable public contract).
    client = gateway._client
    assert getattr(client, "_endpoint", None) == "http://localhost:11434"
    assert getattr(client, "_timeout", None) == 99.0
    assert getattr(client, "_chat_read_timeout", None) == 88.0


@pytest.mark.parametrize(
    "llm_id",
    [
        "ollama-directml",
        "ipex-llm-ollama",
    ],
)
def test_build_llm_phase2_raises(llm_id: str) -> None:
    """Every Phase 2 LLM id raises ``NotImplementedError`` with /Phase 2/."""
    if llm_id == "ollama-directml":
        profile = HwProfile(
            vendor="amd",
            cpu_brand="AMD Ryzen 9 8945HX",
            dgpu=None,
            igpu=None,
            npu="hawk_point",
            vram_mb=None,
            ryzen_ai_gen=1,
            openvino_devices=(),
            has_directml=True,
            has_cuda=False,
            cuda_device_count=0,
        )
        stt_id = "amd-whispercpp-dml"
        text_embed_id = "ollama-bge-m3-cpu"
    else:  # ipex-llm-ollama → Intel iGPU
        profile = HwProfile(
            vendor="intel",
            cpu_brand="Intel Core Ultra 7 155H",
            dgpu=None,
            igpu="Intel iGPU",
            npu=None,
            vram_mb=None,
            ryzen_ai_gen=None,
            openvino_devices=("CPU", "GPU"),
            has_directml=False,
            has_cuda=False,
            cuda_device_count=0,
        )
        stt_id = "openvino-whisper-igpu"
        text_embed_id = "openvino-bge-m3-igpu"

    plan = BackendPlan(
        stt_id=stt_id,
        diarize_id="sherpa-onnx-cpu",
        llm_id=llm_id,
        text_embed_id=text_embed_id,
        hw_profile=profile,
        reason=f"Phase 2 llm_id={llm_id} on {profile.vendor} host",
    )
    ollama_cfg = OllamaSettings()

    with pytest.raises(NotImplementedError) as exc_info:
        BackendFactory().build_llm_gateway(plan, ollama_cfg)
    assert "Phase 2" in str(exc_info.value)
    assert llm_id in str(exc_info.value)


# ---------------------------------------------------------------------------
# build_text_embedder
# ---------------------------------------------------------------------------


def test_build_text_embedder_cpu() -> None:
    """``ollama-bge-m3-cpu`` → ``_OllamaTextEmbedder`` bound to the configured model.

    Forwards ``embed(text)`` to the underlying gateway with the model name
    fixed to ``ollama_cfg.embedding_model``.
    """
    import asyncio

    ollama_cfg = OllamaSettings(
        endpoint="http://localhost:11434",
        embedding_model="bge-m3",
    )

    embedder = BackendFactory().build_text_embedder(_cuda_plan(), ollama_cfg)

    assert isinstance(embedder, _OllamaTextEmbedder)
    assert embedder.model == "bge-m3"
    assert isinstance(embedder.gateway, OllamaGateway)

    # Verify the call forwarding without spinning up Ollama: swap the
    # gateway with a fake whose ``embed`` records the args. We construct
    # the embedder by hand on a fake gateway since the factory's gateway
    # talks HTTP to Ollama which we don't want to hit.
    captured: dict[str, Any] = {}

    class _FakeGateway:
        async def embed(self, *, model: str, text: str) -> list[float]:
            captured["model"] = model
            captured["text"] = text
            return [0.1, 0.2, 0.3]

    plain = _OllamaTextEmbedder(_FakeGateway(), "bge-m3")  # type: ignore[arg-type]
    vec = asyncio.run(plain.embed("hello"))
    assert vec == [0.1, 0.2, 0.3]
    assert captured == {"model": "bge-m3", "text": "hello"}


@pytest.mark.parametrize(
    "text_embed_id",
    [
        "openvino-bge-m3-igpu",
        "openvino-bge-m3-npu",
    ],
)
def test_build_text_embedder_phase2_raises(text_embed_id: str) -> None:
    """Every Phase 2 TEXT_EMBED id raises ``NotImplementedError`` with /Phase 2/ AND id.

    ``factory.py`` declares ``openvino-bge-m3-igpu`` / ``openvino-bge-m3-npu``
    as Phase 2; the error message must include the substring ``"Phase 2"`` AND
    the requested id (same contract as STT / LLM raises) so the Acceleration
    tab / startup log can surface which backend was attempted without parsing
    role / host context.
    """
    if text_embed_id == "openvino-bge-m3-npu":
        profile = HwProfile(
            vendor="intel",
            cpu_brand="Intel Core Ultra 7 155H",
            dgpu=None,
            igpu="Intel iGPU",
            npu="Intel NPU",
            vram_mb=None,
            ryzen_ai_gen=None,
            openvino_devices=("CPU", "GPU", "NPU"),
            has_directml=False,
            has_cuda=False,
            cuda_device_count=0,
        )
        # Planner-coherent pairing: NPU iGPU host pushes STT to openvino-npu and
        # LLM to ipex-llm-ollama. BackendPlan validation only checks ids are in
        # BACKEND_IDS, but using the realistic combo keeps the test honest.
        stt_id = "openvino-whisper-npu"
        llm_id = "ipex-llm-ollama"
    else:  # openvino-bge-m3-igpu — iGPU-only Intel host
        profile = HwProfile(
            vendor="intel",
            cpu_brand="Intel Core Ultra 7 155H",
            dgpu=None,
            igpu="Intel iGPU",
            npu=None,
            vram_mb=None,
            ryzen_ai_gen=None,
            openvino_devices=("CPU", "GPU"),
            has_directml=False,
            has_cuda=False,
            cuda_device_count=0,
        )
        stt_id = "openvino-whisper-igpu"
        llm_id = "ipex-llm-ollama"

    plan = BackendPlan(
        stt_id=stt_id,
        diarize_id="sherpa-onnx-cpu",
        llm_id=llm_id,
        text_embed_id=text_embed_id,
        hw_profile=profile,
        reason=f"Phase 2 text_embed_id={text_embed_id} on {profile.vendor} host",
    )
    ollama_cfg = OllamaSettings()

    with pytest.raises(NotImplementedError) as exc_info:
        BackendFactory().build_text_embedder(plan, ollama_cfg)
    assert "Phase 2" in str(exc_info.value)
    assert text_embed_id in str(exc_info.value)


@pytest.mark.parametrize("pass_gateway", [True, False])
def test_build_text_embedder_gateway_reuse(pass_gateway: bool) -> None:
    """``gateway=`` controls whether a fresh ``OllamaGateway`` is built.

    Phase 1 DI guarantee: at runtime there must be exactly ONE
    ``OllamaGateway`` per process so the LLM gateway and the text embedder
    share a single httpx client. The Factory honours this by accepting an
    optional ``gateway=`` kwarg on ``build_text_embedder``:

    * ``gateway=<existing>`` → reuse it (``embedder.gateway is gateway``).
    * ``gateway=None`` (default) → construct a fresh one each call.

    The DI wiring in ``apps.api.dependencies.build_context`` passes the
    LLM-side gateway so only one instance exists end to end; the no-gateway
    branch keeps the Factory usable as a stand-alone utility (e.g. unit
    tests, MCP server, ad-hoc scripts).
    """
    ollama_cfg = OllamaSettings(
        endpoint="http://localhost:11434",
        embedding_model="bge-m3",
    )
    factory = BackendFactory()
    if pass_gateway:
        shared = factory._build_ollama_gateway(ollama_cfg)
        embedder = factory.build_text_embedder(
            _cuda_plan(), ollama_cfg, gateway=shared
        )
        assert isinstance(embedder, _OllamaTextEmbedder)
        # The wrapper exposes the underlying gateway via the ``gateway``
        # property — same instance, no duplicate httpx client.
        assert embedder.gateway is shared
    else:
        embedder = factory.build_text_embedder(_cuda_plan(), ollama_cfg)
        embedder2 = factory.build_text_embedder(_cuda_plan(), ollama_cfg)
        assert isinstance(embedder, _OllamaTextEmbedder)
        assert isinstance(embedder2, _OllamaTextEmbedder)
        # Without an explicit gateway, each call builds its OWN — the two
        # embedders are not bound to the same gateway instance.
        assert embedder.gateway is not embedder2.gateway
