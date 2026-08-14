from pathlib import Path

import pytest

from spendscope.processing.file_validator import ReceiptFileValidator
from spendscope.processing.inbox import InboxScanner


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    path = tmp_path / "Inbox"
    path.mkdir()
    return path


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("one.jpg", b"\xff\xd8\xffdata"),
        ("two.JPEG", b"\xff\xd8\xffdata"),
        ("three.png", b"\x89PNG\r\n\x1a\ndata"),
        ("four.pdf", b"%PDF-1.7 data"),
    ],
)
def test_validator_accepts_supported_signatures(inbox: Path, name: str, content: bytes) -> None:
    path = inbox / name
    path.write_bytes(content)
    assert ReceiptFileValidator(inbox, max_size_bytes=100).validate(path).valid


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("empty.pdf", b"", "empty"),
        ("notes.txt", b"hello", "unsupported"),
        ("fake.jpg", b"not an image", "does not match"),
        ("large.pdf", b"%PDF-" + b"x" * 100, "size limit"),
    ],
)
def test_validator_rejects_unsafe_or_invalid_files(
    inbox: Path, name: str, content: bytes, reason: str
) -> None:
    path = inbox / name
    path.write_bytes(content)
    result = ReceiptFileValidator(inbox, max_size_bytes=50).validate(path)
    assert not result.valid
    assert reason in (result.reason or "")


def test_validator_rejects_outside_file_and_bad_limit(inbox: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7")
    validator = ReceiptFileValidator(inbox, max_size_bytes=100)
    assert validator.validate(outside).reason == "file is outside the Inbox"
    with pytest.raises(ValueError):
        ReceiptFileValidator(inbox, max_size_bytes=0)


def test_scanner_sorts_files_and_ignores_directories_and_hidden_files(inbox: Path) -> None:
    (inbox / "b.pdf").write_bytes(b"%PDF-1.7")
    (inbox / "A.pdf").write_bytes(b"%PDF-1.7")
    (inbox / ".hidden.pdf").write_bytes(b"%PDF-1.7")
    (inbox / "folder").mkdir()

    entries = InboxScanner(inbox, max_size_bytes=100).scan()
    assert [entry.path.name for entry in entries] == ["A.pdf", "b.pdf"]
    assert InboxScanner(inbox / "missing", max_size_bytes=100).scan() == []
