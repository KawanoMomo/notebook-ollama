import pytest

from core.ollama.models_info import has_vision_capability


def test_has_vision_capability_true():
    assert has_vision_capability(["completion", "vision"]) is True


def test_has_vision_capability_false():
    assert has_vision_capability(["completion"]) is False


def test_has_vision_capability_empty():
    assert has_vision_capability([]) is False


def test_has_vision_capability_case_insensitive():
    assert has_vision_capability(["Vision"]) is True


@pytest.mark.asyncio
async def test_probe_vision_capability_caches(monkeypatch):
    from core.ollama import gateway as gw_mod

    gw_mod.reset_vision_capability_cache()
    calls = []

    class FakeClient:
        async def show(self, model):
            calls.append(model)
            return {"capabilities": ["completion", "vision"]}

    client = FakeClient()
    r1 = await gw_mod.probe_vision_capability(client, "qwen3-vl")
    r2 = await gw_mod.probe_vision_capability(client, "qwen3-vl")
    assert r1 is True
    assert r2 is True
    assert len(calls) == 1  # 2回目はキャッシュ


@pytest.mark.asyncio
async def test_probe_vision_capability_false_for_text_only_model():
    from core.ollama import gateway as gw_mod

    gw_mod.reset_vision_capability_cache()

    class FakeClient:
        async def show(self, model):
            return {"capabilities": ["completion", "chat"]}

    result = await gw_mod.probe_vision_capability(FakeClient(), "qwen2.5:14b")
    assert result is False
