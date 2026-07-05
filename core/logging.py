"""構造化ロギング + last-session.log のリングバッファジャーナル。

spec §7.2 / plan Sprint 4 Task 4.1。

`configure_logging(logs_dir=...)` に ``logs_dir`` を渡すと、構造化ログを
``<logs_dir>/last-session.log`` に redact 済み JSON-lines で追記する。
プロセス起動時に旧 last-session.log を ``.prev`` に世代退避する
(`rotate_last_session`) ので、unclean shutdown 検知時は ``.prev`` を tail する
だけで前回セッションの末尾ログが採取できる (`tail_last_session`)。

設計方針:
- file sink は構造化ログ chain の最後 (JSONRenderer の直前) に挿入される
  processor として実装する。これにより stderr 出力 (JSONRenderer の出力)
  とは独立に、redact 済み版を file に書き出せる。
- file への書き出しは ``redact_log_event`` を必ず通す。spec §6.2 の
  ホワイトリスト方式で、PII (chunk_text, prompt, hostname など) が
  last-session.log に永続化されることを構造的に防ぐ。
- ファイル世代は 1 つだけ (``.prev``)。それより古いものは捨てる。
- 書き込みは "open / write / close" を毎回行う。性能より「クラッシュ直前の
  ログまで確実にディスクへ落ちている」ことを優先する。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

import structlog
from structlog.typing import Processor

from core.crash_reporter.redactor import redact_log_event

_LAST_SESSION_FILENAME = "last-session.log"
_PREV_SESSION_FILENAME = "last-session.log.prev"

_file_lock = threading.Lock()
"""file sink 用 lock。複数スレッド/async タスクからの同時書き込みを直列化。"""


def _make_file_sink_processor(log_path: Path) -> Processor:
    """``last-session.log`` に redact 済み JSON 行を side-write する processor。

    structlog の event_dict を受け取り、
    - structlog 既定の ``"event"`` キーを spec のホワイトリスト名 ``"event_name"``
      に正規化したうえで :func:`redact_log_event` に通す。
    - redact 結果が ``None`` (BLOCKED キー検出) なら **行ごと破棄**。
    - そうでなければ JSON 1 行として ``log_path`` に追記する。

    どんなエラーでもアプリケーションを止めてはいけないので、ファイル書き込み
    時の例外は飲み込む (logging が壊れて app が死ぬのは本末転倒)。

    元の event_dict は変更せずそのまま返す → 後続の JSONRenderer (stderr 出力)
    には structlog の元のフィールド構成のまま流れる。
    """

    def processor(_logger: Any, _method_name: str, event_dict: dict) -> dict:
        try:
            normalized = dict(event_dict)
            # structlog 既定の "event" → spec の "event_name" にマップ
            if "event" in normalized and "event_name" not in normalized:
                normalized["event_name"] = normalized.pop("event")
            redacted = redact_log_event(normalized)
            if redacted is None:
                return event_dict
            line = json.dumps(redacted, ensure_ascii=False, default=str)
            with _file_lock:
                # mkdir はベストエフォート: rotate_last_session が先に作って
                # いる想定だが、外部が削除した場合に備えて毎回 ensure する。
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(line)
                    f.write("\n")
        except Exception:  # noqa: S110 — logging must never break the app
            pass
        return event_dict

    return processor


def rotate_last_session(logs_dir: Path) -> None:
    """前回セッションの ``last-session.log`` を ``.prev`` に世代退避する。

    呼び出されるタイミング: アプリケーション起動時 (``configure_logging`` 内)。

    - ``logs_dir`` が無ければ作る (初回起動)。
    - ``last-session.log`` が無ければ何もしない (これも初回起動)。
    - 既存の ``last-session.log.prev`` は上書きする (世代は 1 つだけ保持)。
    - 退避は ``os.replace`` で行うため、宛先が存在しても atomic に置き換わる。
    """
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    src = logs_dir / _LAST_SESSION_FILENAME
    if not src.exists():
        return
    dst = logs_dir / _PREV_SESSION_FILENAME
    # os.replace は dst が存在しても atomic に上書きする (POSIX/Win 両対応)
    os.replace(src, dst)


def tail_last_session(data_dir: Path, lines: int = 100) -> list[dict]:
    """前回セッションの末尾 N 行 (``.prev``) を dict 列で返す。

    spec §7.2 で unclean shutdown 検知時にクラッシュレポート組み立てに使う。

    動作:
    - ``<data_dir>/logs/last-session.log.prev`` を読む。
    - 各行を JSON parse し、parse 失敗 / dict でない行は silent skip。
    - 最終 ``lines`` 行 (parse 後ではなく **生の行**) を対象に skim する。
    - ファイル不在・dir 不在 / IO エラーは ``[]`` を返す (例外を投げない)。

    Args:
        data_dir: アプリの ``data_dir`` (``logs/`` の親)。
        lines: 末尾何行ぶん見るか。デフォルト 100。

    Returns:
        parse できた dict 行のリスト。順序はファイル内の出現順。
    """
    path = Path(data_dir) / "logs" / _PREV_SESSION_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # ファイル末尾 N 行だけ採取 (頭の方は捨てて良い)
    raw_lines = text.splitlines()
    if lines > 0:
        raw_lines = raw_lines[-lines:]
    out: list[dict] = []
    for raw in raw_lines:
        s = raw.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def configure_logging(
    level: str = "INFO",
    stream: TextIO | None = None,
    *,
    logs_dir: Path | None = None,
) -> None:
    """構造化ログを設定する。``logs_dir`` 指定で last-session.log に追記。

    Args:
        level: ログレベル ("INFO" / "DEBUG" / ...)。
        stream: stderr 以外に流したい場合のストリーム (テストで StringIO 渡す等)。
        logs_dir: 指定された場合のみ ``<logs_dir>/last-session.log`` に
            redact 済み JSON 行を追記する。指定時は配下を mkdir し、既存ファイル
            を ``.prev`` に世代退避する (`rotate_last_session`)。
    """
    target = stream or sys.stderr
    handler = logging.StreamHandler(target)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    # 開発者モードの吸い口(uvicorn アクセスログ・例外)。ring が disabled の
    # 間は emit 先頭の 1 チェックで抜けるため常設してよい(NFR-1)。
    from core.dev_logs.broker import broker as _dev_broker
    from core.dev_logs.ring import ring as _dev_ring
    from core.dev_logs.sink import DevSinkHandler
    root.handlers = [handler, DevSinkHandler(ring=_dev_ring, broker=_dev_broker)]
    root.setLevel(level.upper())

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    # 開発者モード: structlog イベントの吸い口(素通し processor、NFR-1)
    from core.dev_logs.sink import make_dev_structlog_processor
    processors.append(
        make_dev_structlog_processor(ring=_dev_ring, broker=_dev_broker)
    )
    if logs_dir is not None:
        logs_dir = Path(logs_dir)
        # 起動時の世代退避: 前回セッションの last-session.log を .prev に押し出す
        rotate_last_session(logs_dir)
        log_path = logs_dir / _LAST_SESSION_FILENAME
        # JSONRenderer は string を返す terminal processor なので、その前に
        # side-write 用 processor を差し込む。
        processors.append(_make_file_sink_processor(log_path))
    processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(file=target),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name) if name else structlog.get_logger()
