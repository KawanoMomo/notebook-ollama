from core.mcp.tools.list_notebooks import list_notebooks_tool
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source


def test_list_notebooks_returns_id_name_description_source_count(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    a = create_notebook(conn, name="A", description="desc")
    create_source(conn, notebook_id=a.id, kind="md", content_hash="h1")
    create_source(conn, notebook_id=a.id, kind="md", content_hash="h2")
    out = list_notebooks_tool(conn)
    assert out == {
        "notebooks": [
            {
                "id": a.id,
                "name": "A",
                "description": "desc",
                "default_model": None,
                "source_count": 2,
            },
        ]
    }
