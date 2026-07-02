"""last-session.log handler / rotation / tail tests.

spec §7.2 / plan Sprint 4 Task 4.1.

last-session.log は「前回 unclean shutdown 検知時にクラッシュレポートへ tail
100 行を埋め込む」ためのリングバッファ用ジャーナル。
- 起動時に旧 last-session.log を ``.prev`` にローテーション
- 新しいセッションは last-session.log に追記
- 検知時に ``.prev`` を tail して dict 列にして返す
- 書き出し時に ``redact_log_event`` を通すため PII がファイルに残らない
"""
from __future__ import annotations

import json
from pathlib import Path

from core.logging import (
    configure_logging,
    get_logger,
    rotate_last_session,
    tail_last_session,
)

# ----------------------------------------------------------------------------
# rotation
# ----------------------------------------------------------------------------


def test_rotate_moves_last_session_to_prev(tmp_path: Path) -> None:
    """既存 last-session.log は rotate() で .prev に退避され、.log は消える。"""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    last = logs_dir / "last-session.log"
    last.write_text('{"event_name":"old"}\n', encoding="utf-8")

    rotate_last_session(logs_dir)

    assert not last.exists()
    prev = logs_dir / "last-session.log.prev"
    assert prev.exists()
    assert prev.read_text(encoding="utf-8") == '{"event_name":"old"}\n'


def test_rotate_overwrites_older_prev(tmp_path: Path) -> None:
    """更に古い .prev があっても今回の .log で上書きされる (世代は 1 つだけ)。"""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "last-session.log").write_text("new\n", encoding="utf-8")
    (logs_dir / "last-session.log.prev").write_text("ancient\n", encoding="utf-8")

    rotate_last_session(logs_dir)

    assert (logs_dir / "last-session.log.prev").read_text(encoding="utf-8") == "new\n"
    assert not (logs_dir / "last-session.log").exists()


def test_rotate_is_noop_when_no_log(tmp_path: Path) -> None:
    """last-session.log が無い (初回起動) → ローテーション不要・例外も無い。"""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    # should not raise
    rotate_last_session(logs_dir)

    assert not (logs_dir / "last-session.log.prev").exists()
    assert not (logs_dir / "last-session.log").exists()


def test_rotate_auto_creates_logs_dir(tmp_path: Path) -> None:
    """logs/ ディレクトリが無くても rotate は失敗しない (mkdir される)。"""
    logs_dir = tmp_path / "logs"
    # logs_dir は事前に作らない

    rotate_last_session(logs_dir)

    assert logs_dir.is_dir()


# ----------------------------------------------------------------------------
# configure_logging + tail integration (real structlog writes)
# ----------------------------------------------------------------------------


def test_writes_log_records_to_last_session_file(tmp_path: Path) -> None:
    """log.info(...) が last-session.log に JSON-lines で追記される。"""
    data_dir = tmp_path
    logs_dir = data_dir / "logs"
    configure_logging(level="INFO", logs_dir=logs_dir)

    log = get_logger("test_writes_log_records_to_last_session_file")
    log.info("first", duration_ms=10)
    log.info("second", duration_ms=20)

    # rotate so .log は .prev に行く → tail_last_session は .prev を見るため
    rotate_last_session(logs_dir)

    out = tail_last_session(data_dir)
    assert len(out) >= 2
    names = [d.get("event_name") for d in out]
    assert "first" in names
    assert "second" in names
    # ordering: file は追記なので first → second の順で並ぶ
    assert names.index("first") < names.index("second")


def test_tail_respects_lines_parameter(tmp_path: Path) -> None:
    """lines=N で最後の N 行だけが返る。"""
    data_dir = tmp_path
    logs_dir = data_dir / "logs"
    logs_dir.mkdir()
    prev = logs_dir / "last-session.log.prev"
    raw = "\n".join(
        json.dumps({"event_name": f"e{i}", "level": "info"}) for i in range(10)
    )
    prev.write_text(raw + "\n", encoding="utf-8")

    out = tail_last_session(data_dir, lines=3)

    assert len(out) == 3
    assert [d["event_name"] for d in out] == ["e7", "e8", "e9"]


def test_tail_skips_malformed_lines(tmp_path: Path) -> None:
    """外部エディタ等が混ぜた非 JSON 行は silent skip。"""
    data_dir = tmp_path
    logs_dir = data_dir / "logs"
    logs_dir.mkdir()
    prev = logs_dir / "last-session.log.prev"
    content = (
        json.dumps({"event_name": "good1", "level": "info"}) + "\n"
        + "this is not json at all\n"
        + "\n"  # blank line
        + json.dumps({"event_name": "good2", "level": "info"}) + "\n"
        + "{not closed\n"  # truncated json
    )
    prev.write_text(content, encoding="utf-8")

    out = tail_last_session(data_dir)

    assert [d["event_name"] for d in out] == ["good1", "good2"]


def test_tail_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """初回起動 (前セッションが無い) → 空リスト・例外なし。"""
    data_dir = tmp_path
    # tmp_path/logs/last-session.log.prev は存在しない

    assert tail_last_session(data_dir) == []


def test_tail_handles_missing_logs_dir(tmp_path: Path) -> None:
    """logs ディレクトリ自体が存在しなくても [] を返す。"""
    data_dir = tmp_path / "nonexistent"  # 親ごと存在しない

    assert tail_last_session(data_dir) == []


# ----------------------------------------------------------------------------
# redactor integration
# ----------------------------------------------------------------------------


def test_log_record_with_blocked_key_is_dropped(tmp_path: Path) -> None:
    """BLOCKED_LOG_KEYS を含むレコードは last-session.log に書かれない。

    spec §6.2 のホワイトリスト方式を file sink でも徹底する。
    """
    data_dir = tmp_path
    logs_dir = data_dir / "logs"
    configure_logging(level="INFO", logs_dir=logs_dir)

    log = get_logger("test_log_record_with_blocked_key_is_dropped")
    log.info("safe_event", duration_ms=10)
    log.info("leaky_event", chunk_text="TOP_SECRET_LEAK")

    rotate_last_session(logs_dir)
    out = tail_last_session(data_dir)

    names = [d.get("event_name") for d in out]
    assert "safe_event" in names
    assert "leaky_event" not in names

    # 念のため: TOP_SECRET_LEAK の文字列が一切ファイルに残っていないこと
    prev = logs_dir / "last-session.log.prev"
    assert "TOP_SECRET_LEAK" not in prev.read_text(encoding="utf-8")


def test_log_record_strips_non_whitelisted_top_level_keys(tmp_path: Path) -> None:
    """ホワイトリスト外のキー (e.g. arbitrary user field) は落とされる。

    BLOCKED に当たらないがホワイトリスト外のキーは破棄される (drop はしない)。
    """
    data_dir = tmp_path
    logs_dir = data_dir / "logs"
    configure_logging(level="INFO", logs_dir=logs_dir)

    log = get_logger("test_log_record_strips_non_whitelisted_top_level_keys")
    log.info("evt", duration_ms=5, totally_made_up_field="should_be_dropped")

    rotate_last_session(logs_dir)
    out = tail_last_session(data_dir)

    names = [d.get("event_name") for d in out]
    assert "evt" in names
    matching = [d for d in out if d.get("event_name") == "evt"]
    assert matching, "expected event 'evt' to be written"
    assert "totally_made_up_field" not in matching[0]
    assert matching[0].get("duration_ms") == 5


def test_configure_logging_without_logs_dir_does_not_write_file(tmp_path: Path) -> None:
    """logs_dir=None なら従来通り stderr のみ。ファイル sink は無効。"""
    # 旧 API 互換: logs_dir を渡さなければファイルは作られない
    from io import StringIO
    buffer = StringIO()
    configure_logging(level="INFO", stream=buffer)
    log = get_logger("test_configure_logging_without_logs_dir_does_not_write_file")
    log.info("noop")

    # tmp_path 配下に何もファイルが作られていないこと
    assert not (tmp_path / "logs").exists()
    # ただし stream には JSON 1 行が流れていること
    line = buffer.getvalue().strip().splitlines()[-1]
    assert json.loads(line)["event"] == "noop"


# ----------------------------------------------------------------------------
# regression locks (adversarial review gaps — Sprint 4 Task 4.1)
# ----------------------------------------------------------------------------


def test_file_sink_is_thread_safe_under_concurrent_writes(tmp_path: Path) -> None:
    """16 スレッド x 50 書き込みでも 800 行が無傷で残る (_file_lock の保護)。

    file sink は ``_file_lock`` で write を直列化している。これが外れると
    JSONL 行同士が割り込み合って壊れる (途中で改行が紛れる / 行が結合する)。
    本テストは並行書き込みでも 1 行 1 record が確実に保たれることを固定する。
    """
    import io
    import threading

    logs_dir = tmp_path / "logs"
    # stderr 流出を黙らせる (テスト出力ノイズ防止)
    buffer = io.StringIO()
    configure_logging(level="INFO", stream=buffer, logs_dir=logs_dir)

    threads_count = 16
    writes_per_thread = 50
    total = threads_count * writes_per_thread  # 800

    log = get_logger("test_file_sink_is_thread_safe_under_concurrent_writes")

    def worker(tid: int) -> None:
        for j in range(writes_per_thread):
            # event は ALLOWED_LOG_FIELDS の "event_name" に正規化される
            # count は ALLOWED_LOG_FIELDS なので残る
            log.info(f"t{tid}_msg{j}", count=tid * 1000 + j)

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(threads_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # rotate → tail で読み出し
    rotate_last_session(logs_dir)
    prev = logs_dir / "last-session.log.prev"
    raw_text = prev.read_text(encoding="utf-8")
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    assert len(lines) == total, (
        f"expected {total} JSONL records, got {len(lines)} — file sink lost / "
        "corrupted records under concurrency"
    )
    # 各行が JSON dict として parse できて、期待フィールドが揃っていること
    for i, ln in enumerate(lines):
        obj = json.loads(ln)  # 例外 → corruption
        assert isinstance(obj, dict), f"line {i} parsed but not a dict: {obj!r}"
        assert "event_name" in obj, f"line {i} missing event_name: {obj!r}"
        assert obj.get("level") == "info", f"line {i} missing/wrong level: {obj!r}"
        assert "timestamp" in obj, f"line {i} missing timestamp: {obj!r}"


def test_log_message_with_embedded_newlines_preserves_jsonl_boundary(
    tmp_path: Path,
) -> None:
    r"""event 文字列に改行が含まれても JSONL 1 行構造は壊れない (json.dumps の escape)。

    naive な「文字列をそのまま書く」実装だと、event_name に ``\n`` が含まれた
    時点で見かけ上 2 行に見えてしまい、tail パーサが record を見失う。
    file sink は ``json.dumps(..., ensure_ascii=False)`` 経由でシリアライズ
    するため改行は ``\n`` にエスケープされる — その性質をここで固定する。
    """
    import io

    logs_dir = tmp_path / "logs"
    buffer = io.StringIO()
    configure_logging(level="INFO", stream=buffer, logs_dir=logs_dir)

    log = get_logger("test_log_message_with_embedded_newlines_preserves_jsonl_boundary")
    multiline_event = "line1\nline2\nline3"
    log.info(multiline_event, count=1)

    rotate_last_session(logs_dir)
    prev = logs_dir / "last-session.log.prev"
    raw = prev.read_text(encoding="utf-8")

    # 末尾改行を除いた "物理行" は 1 行であるべき
    physical_lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(physical_lines) == 1, (
        f"expected exactly 1 JSONL line; got {len(physical_lines)}: {physical_lines!r}"
    )
    obj = json.loads(physical_lines[0])
    # 元の埋め込み改行が record 内に保存されていること (escape されただけで欠落していない)
    assert obj.get("event_name") == multiline_event


def test_tail_last_session_accepts_str_data_dir_in_addition_to_path(
    tmp_path: Path,
) -> None:
    """``tail_last_session`` / ``rotate_last_session`` は str も受ける (内部 Path 強制変換)。

    呼び出し側がうっかり ``str`` を渡しても落ちないように、両 API は
    内部で ``Path(...)`` に変換している。型ヒント上は ``Path`` だが実運用で
    ``str`` が混入するケース (config 由来のパス等) でも壊れないことを固定する。
    """
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    prev = logs_dir / "last-session.log.prev"
    raw = "\n".join(
        json.dumps({"event_name": f"e{i}", "level": "info"}) for i in range(5)
    )
    prev.write_text(raw + "\n", encoding="utf-8")

    out_path = tail_last_session(tmp_path, lines=5)
    out_str = tail_last_session(str(tmp_path), lines=5)
    assert out_path == out_str
    assert [d["event_name"] for d in out_str] == ["e0", "e1", "e2", "e3", "e4"]

    # rotate も str を受ける: last-session.log を作って .prev に押し出されることを確認
    (logs_dir / "last-session.log").write_text("fresh\n", encoding="utf-8")
    rotate_last_session(str(logs_dir))
    assert not (logs_dir / "last-session.log").exists()
    assert (
        (logs_dir / "last-session.log.prev").read_text(encoding="utf-8") == "fresh\n"
    )


def test_redactor_drops_log_event_with_nested_blocked_key(tmp_path: Path) -> None:
    """ホワイトリストキー (``model``) の値にネストされた禁止キーがあれば行ごと破棄。

    Sprint 1 fix で ``_has_blocked_key_recursive`` が導入された。
    file sink processor 経由でもこの再帰検出が効いていることを固定し、
    将来 ``redact_log_event`` の呼び出しが浅い検出に差し戻されたら検知する。
    """
    import io

    logs_dir = tmp_path / "logs"
    buffer = io.StringIO()
    configure_logging(level="INFO", stream=buffer, logs_dir=logs_dir)

    log = get_logger("test_redactor_drops_log_event_with_nested_blocked_key")
    # model は ALLOWED_LOG_FIELDS にあるホワイトリストキーだが、
    # その値の dict 内に BLOCKED_LOG_KEYS の "chunk_text" がネストされている。
    # 再帰検出が効いていれば行ごと drop されるはず。
    log.info(
        "nested_leak",
        model={"name": "qwen", "chunk_text": "SECRET_NESTED_PAYLOAD"},
    )

    rotate_last_session(logs_dir)
    prev = logs_dir / "last-session.log.prev"
    # ファイル自体は side-write すらされない or 0 行であるべき
    if prev.exists():
        physical_lines = [
            ln
            for ln in prev.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    else:
        physical_lines = []
    assert physical_lines == [], (
        "nested chunk_text inside whitelisted 'model' should have caused the "
        f"entire record to be dropped; got: {physical_lines!r}"
    )
    # tail でも 0 件
    out = tail_last_session(tmp_path)
    assert out == []
