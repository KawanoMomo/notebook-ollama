"""フィードバックハブ HTTP ルータ (お知らせ / 未読数 / ご意見送信).

spec §7.1 / plan Sprint 3 Task 3.7。

Endpoints:
- ``GET  /api/feedback-hub/notices``       — ``data/notices.json`` を返す。
- ``GET  /api/feedback-hub/unread-count``  — 未送信クラッシュ数を返す
  (お知らせ未読は localStorage で FE 管理)。
- ``POST /api/feedback-hub/feedback``      — GitHub Issue 起票 prefill URL を返す。

設計メモ:
- 入力検証は Pydantic で行い、レジストリ外 (``kind``/``sentiment``) を 422 で弾く。
  formatter 側にも同じ検証があり、二重防衛になっている。
- ``notices.json`` のパスは ``Path(__file__).resolve().parents[3] / "data" /
  "notices.json"`` を **遅延** 解決する (テストで上書きしないため固定で良いが、
  ファイル不在時は ``load_notices`` が ``[]`` を返すので起動を妨げない)。
- ``unread-count`` は pending_store のファイル数を集約して返す。お知らせの
  未読は backend では判定できない (個別端末の localStorage に依存) ため
  count に含めない。FE 側で notices_total - seen_count を足して合算する。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from core.crash_reporter import pending_store
from core.feedback_hub.feedback_formatter import (
    VALID_KINDS,
    VALID_SENTIMENTS,
    build_feedback_issue_url,
)
from core.feedback_hub.notice_store import load_notices

router = APIRouter(prefix="/api/feedback-hub", tags=["feedback-hub"])

# repo_root/data/notices.json を遅延解決。
# apps/api/routers/feedback_hub.py → parents[3] = repo root.
_NOTICES_PATH: Path = Path(__file__).resolve().parents[3] / "data" / "notices.json"


# ---------------------------------------------------------------------------
# Pydantic schemas (router-local: 単一ルータ専用のため schemas/ には出さない)
# ---------------------------------------------------------------------------


class NoticeOut(BaseModel):
    id: str
    date: str
    title: str
    body: str
    subsections: list[dict] | None = None


class NoticesOut(BaseModel):
    notices: list[NoticeOut]


class UnreadCountOut(BaseModel):
    count: int


# Literal は Pydantic で列挙バリデーション (422 を自動で出す)。
# VALID_KINDS / VALID_SENTIMENTS と一致させて単一情報源を維持する
# (registry が増えたらここを更新する責務をテストで検出する)。
KindLiteral = Literal["feature", "complaint", "impression"]
SentimentLiteral = Literal["up", "neutral", "down"]


class FeedbackIn(BaseModel):
    kind: KindLiteral
    # 上限は ~50KB: ユーザがエラーログ全文を貼り付けても受け入れられる範囲。
    # formatter は MAX_URL_LEN を超える分を二分探索で切り詰めるため、
    # 上限を緩めても URL 長は安全に維持される。
    body: str = Field(min_length=1, max_length=50_000)
    sentiment: SentimentLiteral | None = None
    # base64 の生バイナリは URL に乗らない (8KB 制限) ため、現状は
    # 「スクショあり」というシグナルとしてのみ扱う。最大 ~2MB の base64
    # 文字列を受け付ける (フロント側で html2canvas → toDataURL の想定)。
    screenshot_b64: str | None = Field(default=None, max_length=3_000_000)

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, v: str) -> str:
        """空白のみの body を 422 で弾く.

        Pydantic ``min_length=1`` は ``'   '`` / ``'\\n'`` / 全角スペース等を
        通してしまい、下流の ``build_feedback_issue_url`` が ``ValueError`` を
        投げて FastAPI の例外ハンドラで HTTP 500 に化けていた。境界の
        validator 内で ``ValueError`` を投げれば、Pydantic が自動で 422
        (Unprocessable Entity) に変換する。``str.strip()`` は Unicode 空白
        (全角スペース U+3000 含む) を全部食うので、日本語入力にも安全。
        """
        if not v.strip():
            raise ValueError("body must not be blank")
        return v


class FeedbackOut(BaseModel):
    prefill_url: str


# ---------------------------------------------------------------------------
# Registry-sync guard: Pydantic Literal と formatter の frozenset が
# ずれていないことを起動時に保証する (silent registry drift を防ぐ)。
# ---------------------------------------------------------------------------


def _assert_registry_sync() -> None:
    # Literal の値集合と formatter 定数を突合する。
    kind_args = set(KindLiteral.__args__)  # type: ignore[attr-defined]
    sent_args = set(SentimentLiteral.__args__)  # type: ignore[attr-defined]
    assert kind_args == set(VALID_KINDS), (
        f"KindLiteral {kind_args} out of sync with VALID_KINDS {set(VALID_KINDS)}"
    )
    assert sent_args == set(VALID_SENTIMENTS), (
        f"SentimentLiteral {sent_args} out of sync with VALID_SENTIMENTS "
        f"{set(VALID_SENTIMENTS)}"
    )


_assert_registry_sync()


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/notices", response_model=NoticesOut)
async def get_notices() -> NoticesOut:
    """お知らせ一覧 (``data/notices.json``) を date 降順で返す。

    ファイル不在 / 壊れた JSON は ``[]`` (load_notices の方針) を返す。
    """
    notices = load_notices(_NOTICES_PATH)
    return NoticesOut(
        notices=[
            NoticeOut(
                id=n.id,
                date=n.date,
                title=n.title,
                body=n.body,
                subsections=n.subsections,
            )
            for n in notices
        ]
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(request: Request) -> UnreadCountOut:
    """未読 / 未送信件数。

    MVP では「未送信クラッシュレポート数」のみを返す。お知らせ未読は
    localStorage で FE が管理し、`/notices` のレスポンスと突合する。
    """
    data_dir: Path = request.app.state.ctx.config.data_dir
    pending = pending_store.load_all(data_dir)
    return UnreadCountOut(count=len(pending))


@router.post("/feedback", response_model=FeedbackOut)
async def post_feedback(payload: FeedbackIn) -> FeedbackOut:
    """ご意見・ご要望から GitHub Issue 起票 prefill URL を生成する。

    `screenshot_b64` は受け取るが URL には乗らない (8KB 制限)。FE は
    レスポンスの prefill_url で新規タブを開いたあと、ユーザに
    Issue ページ上でドラッグ&ドロップ添付を促す運用とする。
    """
    url = build_feedback_issue_url(
        kind=payload.kind,
        body=payload.body,
        sentiment=payload.sentiment,
        screenshot_url=None,  # base64 は URL に埋め込めない
    )
    return FeedbackOut(prefill_url=url)
