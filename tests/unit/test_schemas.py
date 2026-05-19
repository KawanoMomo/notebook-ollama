import pytest
from pydantic import ValidationError

from apps.api.schemas.notebook import NotebookCreate
from apps.api.schemas.chat import MessageInput
from apps.api.schemas.source import SourceUrlCreate

def test_notebook_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        NotebookCreate(name="")

def test_message_input_rejects_empty_content():
    with pytest.raises(ValidationError):
        MessageInput(content="")

def test_source_url_create_validates_url():
    SourceUrlCreate(url="https://example.com/")
    with pytest.raises(ValidationError):
        SourceUrlCreate(url="not a url")
