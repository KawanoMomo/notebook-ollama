import json
from io import StringIO

from core.logging import configure_logging, get_logger


def test_configure_logging_emits_json_lines(monkeypatch):
    buffer = StringIO()
    configure_logging(level="INFO", stream=buffer)
    log = get_logger("test")
    log.info("event_happened", key="value", count=3)
    line = buffer.getvalue().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "event_happened"
    assert record["key"] == "value"
    assert record["count"] == 3
    assert record["level"] == "info"
    assert "timestamp" in record
