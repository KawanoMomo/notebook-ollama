import pytest

from core.mcp.tools.list_models import list_models_tool
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook


class FakeClient:
    async def list_tags(self):
        return [
            {
                "name": "qwen2.5:14b",
                "size": 1,
                "modified_at": "2026-05-01T00:00:00Z",
                "details": {"family": "qwen", "parameter_size": "14B"},
            }
        ]

    async def show(self, model):
        return {
            "parameters": "num_ctx 32768",
            "details": {"family": "qwen", "parameter_size": "14B"},
        }


@pytest.mark.asyncio
async def test_list_models_returns_models_and_defaults(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N", default_model="qwen2.5:14b")
    out = await list_models_tool(conn=conn, client=FakeClient())
    assert out["models"][0]["name"] == "qwen2.5:14b"
    assert out["models"][0]["context_window"] == 32768
    assert "japanese" in out["models"][0]["recommended_for"]
    assert out["defaults_by_notebook"] == [
        {"notebook_id": nb.id, "name": "N", "default_model": "qwen2.5:14b"},
    ]
