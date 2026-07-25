from core.visual.encoder import TransformersVisualEncoder, visual_extra_available

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10


class FakeBackend:
    """_load_backend() が返すオブジェクトの契約: embed_image/embed_text/close。"""

    def __init__(self):
        self.closed = False
        self.calls: list[str] = []

    def embed_image(self, png: bytes) -> list[float]:
        self.calls.append("image")
        return [1.0, 0.0]

    def embed_text(self, text: str) -> list[float]:
        self.calls.append("text")
        return [0.0, 1.0]

    def close(self) -> None:
        self.closed = True


def _encoder(monkeypatch, *, idle=300.0, clock=None):
    backend = FakeBackend()
    enc = TransformersVisualEncoder(
        model_name="fake-model", idle_unload_seconds=idle,
        monotonic=(clock or (lambda: 0.0)),
    )
    monkeypatch.setattr(enc, "_load_backend", lambda: backend)
    return enc, backend


async def test_lazy_load_and_embed(monkeypatch):
    enc, backend = _encoder(monkeypatch)
    assert enc.loaded is False
    vec = await enc.embed_image(png=PNG)
    assert vec == [1.0, 0.0]
    assert enc.loaded is True
    vec2 = await enc.embed_text(text="query")
    assert vec2 == [0.0, 1.0]
    assert backend.calls == ["image", "text"]


async def test_idle_unload(monkeypatch):
    t = {"now": 0.0}
    enc, backend = _encoder(monkeypatch, idle=300.0, clock=lambda: t["now"])
    await enc.embed_text(text="q")
    t["now"] = 100.0
    assert enc.maybe_unload_if_idle() is False  # まだアイドル閾値前
    assert enc.loaded is True
    t["now"] = 301.0
    assert enc.maybe_unload_if_idle() is True
    assert enc.loaded is False
    assert backend.closed is True


async def test_reload_after_unload(monkeypatch):
    t = {"now": 0.0}
    enc, _backend = _encoder(monkeypatch, idle=10.0, clock=lambda: t["now"])
    await enc.embed_text(text="q")
    t["now"] = 11.0
    enc.maybe_unload_if_idle()
    # アンロード後の呼び出しで再ロードされる
    vec = await enc.embed_image(png=PNG)
    assert vec == [1.0, 0.0]
    assert enc.loaded is True


def test_visual_extra_available_is_bool():
    assert isinstance(visual_extra_available(), bool)
