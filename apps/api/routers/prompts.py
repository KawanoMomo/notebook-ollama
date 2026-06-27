"""プロンプト挿入機能の API ルータ。

固定 3 スロット + プルダウン任意件数 + アイコン画像配信。
画像セキュリティ(MIME magic 判定 / 200KB / SVG XSS / path traversal)は
ここで一括処理。

設計: docs/specs/2026-06-26-prompt-injection-design.md §4, §6.1
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse

from apps.api.schemas.prompts import (
    DropdownOrderUpdate,
    DropdownPromptCreate,
    DropdownPromptOut,
    DropdownPromptUpdate,
    FixedPromptSlotOut,
    FixedPromptSlotUpdate,
    PromptsOut,
)
from core.exceptions import AppError, ErrorCode
from core.prompts import store as prompts_store
from core.prompts.models import PromptsSettings

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# 同時書込みの直列化(複数タブからの並行編集を握りつぶさない設計)。
_LOCK = asyncio.Lock()

_MAX_ICON_BYTES = 200 * 1024  # 200KB
_ICONS_DIRNAME = "prompt-icons"

# uuid v4 形式 + 既知拡張子に厳格にマッチ(path traversal とファイル名偽装を弾く)。
_UUID_FILENAME_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.(?:png|jpg|jpeg|svg)$"
)

# SVG XSS: <script> タグと on* インラインイベントハンドラ。
_SVG_SCRIPT_RE = re.compile(rb"<\s*script\b", re.IGNORECASE)
_SVG_ON_HANDLER_RE = re.compile(rb"\son[a-zA-Z]+\s*=", re.IGNORECASE)

_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/svg+xml": "svg",
}


# --- helpers --------------------------------------------------------------


def _data_dir(request: Request) -> Path:
    return request.app.state.ctx.config.data_dir


def _icons_dir(data_dir: Path) -> Path:
    d = data_dir / _ICONS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _icon_url_for(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/api/prompts/icons/{filename}"


def _to_out(settings: PromptsSettings) -> PromptsOut:
    return PromptsOut(
        fixed=[
            FixedPromptSlotOut(
                title=s.title,
                body=s.body,
                icon_url=_icon_url_for(s.icon_filename),
            )
            for s in settings.fixed
        ],
        dropdown=[
            DropdownPromptOut(id=d.id, title=d.title, body=d.body)
            for d in settings.dropdown
        ],
    )


def _detect_mime(content: bytes) -> str | None:
    """magic bytes で MIME を判定する。失敗すれば None。

    PNG: 89 50 4E 47 0D 0A 1A 0A
    JPEG: FF D8 FF
    SVG: XML 宣言 or <svg を含む(text-ish)
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # SVG: 先頭 4KB 以内に <svg を含む XML
    head = content[:4096].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        if b"<svg" in head:
            return "image/svg+xml"
    return None


def _validate_image(content: bytes, claimed_mime: str | None) -> str:
    """サイズ・MIME・SVG XSS を全部検査して確定 MIME を返す。"""
    if len(content) > _MAX_ICON_BYTES:
        raise AppError(
            ErrorCode.INPUT_PAYLOAD_TOO_LARGE,
            f"image must be <= {_MAX_ICON_BYTES // 1024}KB",
        )
    detected = _detect_mime(content)
    if detected is None:
        raise AppError(
            ErrorCode.INPUT_UNSUPPORTED_MEDIA,
            "only PNG/JPG/SVG are allowed",
        )
    # SVG は中身に script / on-handler を含まないこと
    if detected == "image/svg+xml":
        if _SVG_SCRIPT_RE.search(content) or _SVG_ON_HANDLER_RE.search(content):
            raise AppError(
                ErrorCode.INPUT_INVALID,
                "SVG must not contain scripts or inline event handlers",
            )
    # claimed と detected の不一致は不正(MIME 詐称攻撃)
    if claimed_mime and detected != claimed_mime:
        # JPEG の image/jpg は image/jpeg と等価扱い
        if not (
            detected == "image/jpeg" and claimed_mime in ("image/jpg", "image/jpeg")
        ):
            raise AppError(
                ErrorCode.INPUT_UNSUPPORTED_MEDIA,
                f"declared {claimed_mime} but content is {detected}",
            )
    return detected


def _delete_icon_file_if_exists(data_dir: Path, filename: str | None) -> None:
    if not filename:
        return
    if not _UUID_FILENAME_RE.match(filename):
        return  # 安全側: 形式不正なら何もしない
    target = _icons_dir(data_dir) / filename
    if target.is_file():
        target.unlink()


# --- GET /api/prompts -----------------------------------------------------


@router.get("", response_model=PromptsOut)
async def get_prompts(request: Request) -> PromptsOut:
    return _to_out(prompts_store.load_prompts(_data_dir(request)))


# --- 固定スロット --------------------------------------------------------


@router.put("/fixed/{slot_index}", response_model=PromptsOut)
async def put_fixed_slot(
    request: Request, slot_index: int, body: FixedPromptSlotUpdate
) -> PromptsOut:
    async with _LOCK:
        updated = prompts_store.set_fixed(
            _data_dir(request), slot_index, title=body.title, body=body.body
        )
    return _to_out(updated)


@router.delete("/fixed/{slot_index}", response_model=PromptsOut)
async def delete_fixed_slot(request: Request, slot_index: int) -> PromptsOut:
    data_dir = _data_dir(request)
    async with _LOCK:
        current = prompts_store.load_prompts(data_dir)
        # range 検査は store 側で(0/1/2 以外は AppError(INPUT_INVALID))
        if slot_index in (0, 1, 2):
            _delete_icon_file_if_exists(
                data_dir, current.fixed[slot_index].icon_filename
            )
        updated = prompts_store.clear_fixed(data_dir, slot_index)
    return _to_out(updated)


# --- アイコン ------------------------------------------------------------


@router.post("/fixed/{slot_index}/icon", response_model=PromptsOut)
async def upload_fixed_icon(
    request: Request,
    slot_index: int,
    file: UploadFile = File(...),
) -> PromptsOut:
    data_dir = _data_dir(request)
    content = await file.read()
    detected_mime = _validate_image(content, file.content_type)
    ext = _MIME_TO_EXT[detected_mime]
    new_filename = f"{uuid.uuid4()}.{ext}"
    async with _LOCK:
        current = prompts_store.load_prompts(data_dir)
        # range 検査
        if slot_index not in (0, 1, 2):
            raise AppError(
                ErrorCode.INPUT_INVALID, "slot_index must be 0, 1, or 2"
            )
        # 旧画像を破棄
        _delete_icon_file_if_exists(
            data_dir, current.fixed[slot_index].icon_filename
        )
        # 新画像をディスクへ
        target = _icons_dir(data_dir) / new_filename
        target.write_bytes(content)
        updated = prompts_store.set_fixed_icon(
            data_dir, slot_index, icon_filename=new_filename
        )
    return _to_out(updated)


@router.delete("/fixed/{slot_index}/icon", response_model=PromptsOut)
async def delete_fixed_icon(request: Request, slot_index: int) -> PromptsOut:
    data_dir = _data_dir(request)
    async with _LOCK:
        current = prompts_store.load_prompts(data_dir)
        if slot_index not in (0, 1, 2):
            raise AppError(
                ErrorCode.INPUT_INVALID, "slot_index must be 0, 1, or 2"
            )
        _delete_icon_file_if_exists(
            data_dir, current.fixed[slot_index].icon_filename
        )
        updated = prompts_store.set_fixed_icon(
            data_dir, slot_index, icon_filename=None
        )
    return _to_out(updated)


@router.get("/icons/{filename}")
async def get_icon(request: Request, filename: str) -> FileResponse:
    """画像配信。UUID + 既知拡張子に厳格マッチ → そうでなければ 400。

    Path traversal(`..%2F..%2Fetc%2Fpasswd` 等)は正規表現で構造的に弾く。
    `os.path.basename` 等の defense-in-depth よりも、ファイル名形式の正規化が
    第一防御。
    """
    if not _UUID_FILENAME_RE.match(filename):
        raise AppError(ErrorCode.INPUT_INVALID, "invalid icon filename")
    data_dir = _data_dir(request)
    target = _icons_dir(data_dir) / filename
    if not target.is_file():
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "icon not found")
    return FileResponse(
        target,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- プルダウン CRUD ----------------------------------------------------


@router.post(
    "/dropdown", status_code=201, response_model=DropdownPromptOut
)
async def post_dropdown(
    request: Request, body: DropdownPromptCreate
) -> DropdownPromptOut:
    async with _LOCK:
        new_item = prompts_store.add_dropdown(
            _data_dir(request), title=body.title, body=body.body
        )
    return DropdownPromptOut(
        id=new_item.id, title=new_item.title, body=new_item.body
    )


@router.put("/dropdown/order", response_model=PromptsOut)
async def put_dropdown_order(
    request: Request, body: DropdownOrderUpdate
) -> PromptsOut:
    async with _LOCK:
        updated = prompts_store.reorder_dropdown(_data_dir(request), body.ids)
    return _to_out(updated)


@router.put("/dropdown/{prompt_id}", response_model=DropdownPromptOut)
async def put_dropdown(
    request: Request, prompt_id: str, body: DropdownPromptUpdate
) -> DropdownPromptOut:
    async with _LOCK:
        updated = prompts_store.update_dropdown(
            _data_dir(request), prompt_id, title=body.title, body=body.body
        )
    return DropdownPromptOut(
        id=updated.id, title=updated.title, body=updated.body
    )


@router.delete("/dropdown/{prompt_id}", status_code=204)
async def delete_dropdown(request: Request, prompt_id: str) -> Response:
    async with _LOCK:
        prompts_store.delete_dropdown(_data_dir(request), prompt_id)
    return Response(status_code=204)
