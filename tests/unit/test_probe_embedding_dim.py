import pytest

from core.ollama.gateway import probe_embedding_dim, reset_embedding_dim_cache


class FakeGateway:
    def __init__(self, dim: int) -> None:
        self._dim = dim
        self.calls: list[str] = []

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.calls.append(model)
        return [0.0] * self._dim


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_embedding_dim_cache()
    yield
    reset_embedding_dim_cache()


@pytest.mark.asyncio
async def test_probe_returns_vector_length():
    gw = FakeGateway(dim=768)
    dim = await probe_embedding_dim(gw, "nomic-embed-text")
    assert dim == 768
    assert gw.calls == ["nomic-embed-text"]


@pytest.mark.asyncio
async def test_probe_caches_per_model():
    gw = FakeGateway(dim=1024)
    first = await probe_embedding_dim(gw, "bge-m3")
    second = await probe_embedding_dim(gw, "bge-m3")
    assert first == second == 1024
    # キャッシュヒットで 2 回目は embed を呼ばない
    assert gw.calls == ["bge-m3"]


@pytest.mark.asyncio
async def test_probe_distinct_models_not_shared():
    gw = FakeGateway(dim=512)
    await probe_embedding_dim(gw, "model-a")
    await probe_embedding_dim(gw, "model-b")
    assert gw.calls == ["model-a", "model-b"]
