from core.config import AppConfig


def test_audio_defaults():
    c = AppConfig()
    assert c.audio.whisper_model == "large-v3"
    assert c.audio.device == "cuda"
    assert c.audio.compute_type == "float16"
    assert c.audio.language == "ja"
    assert c.audio.sample_rate == 16000
    assert c.audio.live_caption_default is True
    assert c.audio.agc_enabled is True
    assert c.audio.diarization_enabled is True
    assert c.audio.voiceprint_naming is True
    assert c.audio.name_inference_llm is True
    assert c.audio.name_threshold == 0.65
    assert c.audio.storage_format == "aac"
    assert c.audio.storage_bitrate_kbps == 64
    assert c.audio.keep_audio is True
