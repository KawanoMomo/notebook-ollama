from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.exceptions import AppError, ErrorCode

router = APIRouter(prefix="/api/features", tags=["features"])


class FeatureOptIn(BaseModel):
    enabled: bool


@router.get("")
async def list_features(request: Request) -> dict:
    return {"features": request.app.state.ctx.features.list_flags()}


@router.put("/{flag_id}")
async def put_feature(request: Request, flag_id: str, body: FeatureOptIn) -> dict:
    svc = request.app.state.ctx.features
    svc.set_optin(flag_id, body.enabled)
    return {"features": svc.list_flags()}


def require_feature(flag_id: str):
    """ベータゲート依存。無効時は 403 + 有効化ヒント。"""

    async def _dep(request: Request) -> None:
        if not request.app.state.ctx.features.is_enabled(flag_id):
            raise AppError(
                ErrorCode.FEATURE_DISABLED,
                "この機能はベータ版です",
                remediation="設定の「ベータ機能」で有効化してください",
            )

    return _dep
