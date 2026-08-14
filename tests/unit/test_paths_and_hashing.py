from pathlib import Path

import pytest

from spendscope.utilities.hashing import sha256_file
from spendscope.utilities.paths import collision_safe_path, is_path_within, safe_filename


def test_hashing_is_streamed_and_repeatable(tmp_path: Path) -> None:
    source = tmp_path / "receipt.bin"
    source.write_bytes(b"receipt contents")

    assert sha256_file(source, chunk_size=3) == sha256_file(source)
    with pytest.raises(ValueError):
        sha256_file(source, chunk_size=0)


def test_path_containment_rejects_siblings(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    assert is_path_within(inbox / "receipt.jpg", inbox)
    assert not is_path_within(tmp_path / "other" / "receipt.jpg", inbox)


def test_safe_and_collision_free_names(tmp_path: Path) -> None:
    assert safe_filename("../../strange:name?.jpg") == "strange_name_.jpg"
    existing = tmp_path / "receipt.jpg"
    existing.write_bytes(b"first")
    assert collision_safe_path(tmp_path, "receipt.jpg").name == "receipt-2.jpg"
