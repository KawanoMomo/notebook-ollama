"""Module-level holder for ctx so the mcp ASGI mount can find it.

Populated during the FastAPI lifespan. We avoid using app.state directly because
mounted ASGI apps see their own scope, not the parent FastAPI app's state.
"""
from __future__ import annotations

from typing import Any

ctx: Any = None
