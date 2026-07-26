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


async def test_no_unload_while_embed_in_flight(monkeypatch):
    """回帰テスト: _last_used が埋め込み開始時刻だったため、埋め込み所要時間が
    idle_unload_seconds を超えると watchdog が計算中のバックエンドを解放し、
    ページ毎にロード/アンロードをスラッシングしていた(AC6実機で 20分に8回
    ロードを観測)。実行中は maybe_unload_if_idle が False を返すこと。"""
    import asyncio
    import time as _time

    class SlowBackend(FakeBackend):
        def embed_image(self, png: bytes) -> list[float]:
            _time.sleep(0.15)  # to_thread 内で走る「長い」埋め込み
            return super().embed_image(png)

    t = {"now": 0.0}
    backend = SlowBackend()
    enc = TransformersVisualEncoder(
        model_name="fake-model", idle_unload_seconds=0.01,  # 埋め込みより短いidle
        monotonic=lambda: t["now"],
    )
    monkeypatch.setattr(enc, "_load_backend", lambda: backend)

    task = asyncio.create_task(enc.embed_image(png=PNG))
    await asyncio.sleep(0.05)  # 埋め込みが in-flight の最中
    t["now"] = 100.0  # 開始時刻基準では idle 閾値を大きく超過
    assert enc.maybe_unload_if_idle() is False  # 実行中は解放しない
    assert enc.loaded is True
    assert backend.closed is False
    vec = await task
    assert vec == [1.0, 0.0]
    # 完走後は通常どおり解放できる(完了時刻からのidle判定)
    t["now"] = 300.0
    assert enc.maybe_unload_if_idle() is True


def test_execution_speed_throttling_toggle_is_safe():
    """EcoQoS切替ヘルパー: Windowsでは成功(bool)、失敗時も例外を出さない。
    P-core優先プロファイル(実機観測: E-core飽和でブラウザ競合)の基盤。"""
    from core.visual.encoder import _set_execution_speed_throttling

    result = _set_execution_speed_throttling(disable=True)
    assert isinstance(result, bool)
    # 元に戻す(テストプロセスのQoSを汚さない)
    restored = _set_execution_speed_throttling(disable=False)
    assert isinstance(restored, bool)
