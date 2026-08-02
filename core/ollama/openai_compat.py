"""``OpenAICompatClient`` — OpenAI互換HTTPサーバー用の ``_ClientLike`` 実装。

spec addendum "Update 2026-08-02" §L の第一級実装。llama.cpp ``llama-server`` /
OpenVINO Model Server / Lemonade Server / LM Studio / Foundry Local など、
OpenAI互換API(``/v1/chat/completions`` + ``/v1/embeddings``)を話すローカル
サーバーに、``OllamaGateway`` の ``_client`` 注入だけで透過的に接続する。

設計上の要点:

* ``core.ollama.gateway._ClientLike`` と構造的に一致する(``embed`` /
  ``chat_stream``)。Gateway・上位層(ingestion / retrieval / generation)は
  一切変更しない。
* エラーは ``OllamaClient`` と同じ ``AppError`` コードに正規化する
  (``OLLAMA_UNREACHABLE`` / ``OLLAMA_MODEL_NOT_FOUND`` /
  ``OLLAMA_GENERATION_FAILED``)。上位のエラーハンドリング・remediation 表示が
  そのまま機能する。
* Ollama options は OpenAI パラメータへ最小マッピングする
  (``num_predict``→``max_tokens``、``temperature``、``top_p``)。それ以外の
  Ollama 固有 option(``num_gpu`` / ``num_ctx`` 等)はサーバー側に対応概念が
  無いため黙って捨てず、devログに警告を残す。
* Ollama 形式の vision メッセージ(``{"images": [b64, ...]}``)は OpenAI の
  content-parts 形式(``image_url`` + data URI)へ変換する。
* reasoning 系フィールド(``delta.reasoning_content`` — llama-server / vLLM
  慣行、または ``delta.reasoning``)は ``ThinkingChunk`` として yield し、
  本文と型で区別できるようにする(``OllamaClient`` と同じ契約)。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.exceptions import AppError, ErrorCode
from core.ollama.client import ThinkingChunk


def _emit_dev(level: str, msg: str, payload: dict) -> None:
    """開発者モードへの計装点。disabled 時は 1 チェックで抜ける。"""
    from core.dev_logs.broker import broker as _broker
    from core.dev_logs.ring import ring as _ring
    from core.dev_logs.sink import push_dev_entry
    push_dev_entry(ring=_ring, broker=_broker, level=level, source="ollama",
                   msg=msg, payload=payload)


# Ollama options → OpenAI chat/completions パラメータの対応表。
# ここに無い option はサーバー側に対応概念が無い(dev ログ警告のみ)。
_OPTION_MAP: dict[str, str] = {
    "num_predict": "max_tokens",
    "temperature": "temperature",
    "top_p": "top_p",
}


def _map_options(options: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Ollama options を OpenAI パラメータへ変換し、(params, 無視したキー) を返す。"""
    if not options:
        return {}, []
    params: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in options.items():
        mapped = _OPTION_MAP.get(key)
        if mapped is None:
            dropped.append(key)
            continue
        # num_predict=-1 は Ollama の「無制限」。OpenAI 側は max_tokens 省略が同義。
        if key == "num_predict" and isinstance(value, int) and value < 0:
            continue
        params[mapped] = value
    return params, dropped


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ollama 形式メッセージを OpenAI 形式へ変換する。

    テキストのみのメッセージはそのまま(役割・本文とも共通)。``images``
    キー(base64 文字列のリスト、Ollama vision 形式)を持つメッセージは
    OpenAI の content-parts 形式へ変換する。
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        images = msg.get("images")
        if not images:
            out.append({k: v for k, v in msg.items() if k != "images"})
            continue
        parts: list[dict[str, Any]] = []
        content = msg.get("content", "")
        if content:
            parts.append({"type": "text", "text": content})
        for b64 in images:
            parts.append(
                {
                    "type": "image_url",
                    # 実フォーマットは PNG/JPEG いずれもあり得るが、data URI の
                    # MIME はヒントに過ぎず、実装(llama.cpp 等)はマジック
                    # バイトでデコードする。PNG を代表値として送る。
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        out.append({"role": msg.get("role", "user"), "content": parts})
    return out


class OpenAICompatClient:
    """OpenAI互換サーバーを ``_ClientLike`` として扱う HTTP クライアント。

    ``endpoint`` はサーバーのベース URL(例 ``http://localhost:8080``)。
    ``/v1`` は自動付与する(``.../v1`` まで書かれていても二重付与しない)。
    ``api_key`` は空文字列なら Authorization ヘッダを送らない(ローカル
    サーバーの大半は鍵不要。llama-server ``--api-key`` 運用時のみ設定)。
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str = "",
        timeout: float = 120.0,
        chat_read_timeout: float | None = None,
    ) -> None:
        base = endpoint.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self._endpoint = base
        self._api_key = api_key
        self._timeout = timeout
        self._chat_read_timeout = chat_read_timeout

    # ------------------------------------------------------------------
    # _ClientLike
    # ------------------------------------------------------------------

    async def embed(
        self,
        *,
        model: str,
        text: str,
        options: dict[str, Any] | None = None,
    ) -> list[float]:
        # OpenAI embeddings API に Ollama options の対応概念は無い。
        # (num_gpu=0 の NaN 回避は Ollama 固有の事情で、こちらの経路では不要)
        if options:
            _emit_dev("debug", "embed options ignored (openai-compat)",
                      {"phase": "req", "model": model,
                       "ignored_options": sorted(options)})
        payload = {"model": model, "input": text}
        _emit_dev("debug", "embed req (openai-compat)",
                  {"phase": "req", "model": model, "text": text})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(
                    f"{self._endpoint}/v1/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE,
                    "OpenAI-compatible server unreachable",
                    detail=str(exc),
                ) from exc
        if r.status_code == 404:
            raise AppError(ErrorCode.OLLAMA_MODEL_NOT_FOUND, f"model {model} not found")
        if r.status_code >= 400:
            raise AppError(
                ErrorCode.OLLAMA_GENERATION_FAILED,
                f"openai-compat server returned {r.status_code}",
                detail=r.text,
            )
        data = r.json()
        try:
            embedding = data["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError(
                ErrorCode.OLLAMA_GENERATION_FAILED,
                "openai-compat server returned malformed embeddings response",
                detail=str(data)[:500],
            ) from exc
        _emit_dev("debug", "embed resp (openai-compat)",
                  {"phase": "resp", "model": model, "dim": len(embedding)})
        return embedding

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """SSE ストリームからトークンを逐次 yield する。

        最終チャンクの ``finish_reason`` は ``meta["done_reason"]`` に書き込む
        (``"stop"`` / ``"length"`` は Ollama と同語彙。num_predict 上限による
        打ち切り検知=自動継続 issue #22 がそのまま機能する)。
        """
        params, dropped = _map_options(options)
        if dropped:
            _emit_dev("warn", "chat options dropped (openai-compat)",
                      {"phase": "req", "model": model,
                       "dropped_options": sorted(dropped)})
        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "stream": True,
            **params,
        }
        _emit_dev("info", "chat req (openai-compat)",
                  {"phase": "req", "model": model, "options": options,
                   "messages": messages})
        _t0 = time.monotonic()
        _chunks = 0
        # connect/write/pool は httpx 既定(5s)を維持し、read のみ有限化する。
        timeout = httpx.Timeout(5.0, read=self._chat_read_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self._endpoint}/v1/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        if response.status_code == 404:
                            raise AppError(
                                ErrorCode.OLLAMA_MODEL_NOT_FOUND,
                                f"model {model} not found",
                            )
                        raise AppError(
                            ErrorCode.OLLAMA_GENERATION_FAILED,
                            f"openai-compat server returned {response.status_code}",
                            detail=body.decode(errors="replace"),
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        # llama-server / vLLM 慣行の reasoning フィールド。
                        thinking = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or ""
                        )
                        if thinking:
                            _emit_dev("debug", "chat thinking (openai-compat)",
                                      {"phase": "thinking", "model": model,
                                       "text": thinking})
                            yield ThinkingChunk(thinking)
                        content = delta.get("content") or ""
                        if content:
                            _chunks += 1
                            _emit_dev("debug", "chat chunk (openai-compat)",
                                      {"phase": "chunk", "model": model,
                                       "text": content})
                            yield content
                        finish = choice.get("finish_reason")
                        if finish:
                            if meta is not None:
                                meta["done_reason"] = finish
                            _emit_dev("info", "chat resp (openai-compat)", {
                                "phase": "resp", "model": model,
                                "latency_ms": int((time.monotonic() - _t0) * 1000),
                                "chunks": _chunks,
                                "done_reason": finish,
                            })
            except httpx.HTTPError as exc:
                _emit_dev("error", "chat error (openai-compat)",
                          {"phase": "error", "model": model, "detail": str(exc)})
                raise AppError(
                    ErrorCode.OLLAMA_UNREACHABLE,
                    "OpenAI-compatible server unreachable",
                    detail=str(exc),
                ) from exc

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}


__all__ = ["OpenAICompatClient"]
