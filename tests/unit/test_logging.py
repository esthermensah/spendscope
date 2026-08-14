import logging
from pathlib import Path

from spendscope.logging_config import configure_logging


def test_logging_redacts_sensitive_shapes(tmp_path: Path) -> None:
    log_file = configure_logging(tmp_path)
    logger = logging.getLogger("test")
    logger.warning("authorization=secret-value user@example.com 4111 1111 1111 1111")
    for handler in logging.getLogger().handlers:
        handler.flush()

    contents = log_file.read_text(encoding="utf-8")
    assert "secret-value" not in contents
    assert "user@example.com" not in contents
    assert "4111" not in contents
    assert contents.count("REDACTED") == 3
