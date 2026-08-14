from __future__ import annotations

import json
from io import BytesIO
from typing import Any

import pytest

from spendscope.services.updates import check_for_update


class Response(BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_update_check_reports_newer_release(monkeypatch: Any) -> None:
    payload = json.dumps(
        {"tag_name": "v0.2.0", "html_url": "https://github.com/example/releases/v0.2.0"}
    ).encode()
    monkeypatch.setattr("spendscope.services.updates.urlopen", lambda *_a, **_k: Response(payload))

    result = check_for_update("0.1.0")

    assert result.update_available
    assert result.latest_version == "v0.2.0"


def test_update_check_accepts_current_release(monkeypatch: Any) -> None:
    payload = json.dumps({"tag_name": "v0.1.0"}).encode()
    monkeypatch.setattr("spendscope.services.updates.urlopen", lambda *_a, **_k: Response(payload))

    assert not check_for_update("0.1.0").update_available


def test_update_check_rejects_an_invalid_release_tag(monkeypatch: Any) -> None:
    payload = json.dumps({"tag_name": "latest"}).encode()
    monkeypatch.setattr("spendscope.services.updates.urlopen", lambda *_a, **_k: Response(payload))

    with pytest.raises(ValueError, match="Unsupported release version"):
        check_for_update("0.1.0")
