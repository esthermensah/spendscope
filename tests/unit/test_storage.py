import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from spendscope.config import AppConfig, RetentionPolicy
from spendscope.processing.file_manager import ReceiptFileManager
from spendscope.storage.compression import ImageCompressionError, compress_image
from spendscope.storage.retention import RetentionCandidate, RetentionService
from spendscope.storage.usage import calculate_storage_usage, path_size


def create_image(path: Path, *, size: tuple[int, int] = (3000, 1800)) -> None:
    Image.new("RGB", size, color=(245, 245, 240)).save(path, quality=100)


def test_image_compression_resizes_and_writes_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    destination = tmp_path / "archive" / "receipt.jpg"
    create_image(source)

    result = compress_image(source, destination, max_dimension=1000)

    assert result.dimensions == (1000, 600)
    assert result.archived_size == destination.stat().st_size
    assert 0 < result.ratio < 1
    assert source.exists()


def test_image_compression_rejects_bad_source_and_same_destination(tmp_path: Path) -> None:
    source = tmp_path / "fake.jpg"
    source.write_bytes(b"not an image")
    with pytest.raises(ImageCompressionError):
        compress_image(source, tmp_path / "output.jpg")
    with pytest.raises(ImageCompressionError):
        compress_image(source, source)


def test_file_manager_compresses_confirmed_image_and_handles_collision(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path)
    manager = ReceiptFileManager(config)
    paths = manager.create_workspace()
    first = paths["inbox"] / "receipt.jpg"
    create_image(first)

    archived = manager.archive_confirmed(first, date(2026, 8, 6))
    assert archived.destination == paths["archive"] / "2026" / "08" / "receipt.jpg"
    assert archived.action == "compressed"
    assert not first.exists()

    second = paths["inbox"] / "receipt.jpg"
    create_image(second)
    collision = manager.archive_confirmed(second, date(2026, 8, 6))
    assert collision.destination is not None
    assert collision.destination.name == "receipt-2.jpg"


def test_pdf_is_archived_unchanged_and_review_file_is_not_compressed(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path)
    manager = ReceiptFileManager(config)
    paths = manager.create_workspace()
    pdf = paths["inbox"] / "receipt.pdf"
    pdf.write_bytes(b"%PDF-1.7 unchanged")
    archived = manager.archive_confirmed(pdf, date(2026, 1, 1))
    assert archived.action == "archived"
    assert archived.destination is not None
    assert archived.destination.read_bytes() == b"%PDF-1.7 unchanged"

    review = paths["inbox"] / "review.jpg"
    review.write_bytes(b"unprocessed image bytes")
    moved = manager.move_to_review(review)
    assert moved.action == "needs_review"
    assert moved.destination is not None
    assert moved.destination.read_bytes() == b"unprocessed image bytes"

    reviewed_pdf = paths["inbox"] / "reviewed.pdf"
    reviewed_pdf.write_bytes(b"%PDF-1.7 reviewed")
    review_destination = manager.move_to_review(reviewed_pdf).destination
    assert review_destination is not None
    confirmed = manager.archive_confirmed(review_destination, date(2026, 1, 2))
    assert confirmed.action == "archived"
    assert confirmed.destination is not None
    assert confirmed.destination.parent == paths["archive"] / "2026" / "01"


def test_destructive_policy_requires_confirmation(tmp_path: Path) -> None:
    config = AppConfig(
        root_folder=tmp_path,
        retention_policy=RetentionPolicy.DELETE_AFTER_CONFIRMATION,
    )
    manager = ReceiptFileManager(config)
    source = manager.create_workspace()["inbox"] / "receipt.pdf"
    source.write_bytes(b"%PDF-1.7")
    with pytest.raises(PermissionError):
        manager.archive_confirmed(source, date.today())
    deleted = manager.archive_confirmed(source, date.today(), destructive_confirmed=True)
    assert deleted.action == "deleted"
    assert not source.exists()


def test_delayed_deletion_policy_archives_before_retention_review(tmp_path: Path) -> None:
    config = AppConfig(
        root_folder=tmp_path,
        retention_policy=RetentionPolicy.DELETE_AFTER_30_DAYS,
    )
    manager = ReceiptFileManager(config)
    source = manager.create_workspace()["inbox"] / "receipt.pdf"
    source.write_bytes(b"%PDF-1.7")
    archived = manager.archive_confirmed(source, date.today())
    assert archived.destination is not None and archived.destination.exists()
    assert archived.action == "archived"


def test_file_manager_rejects_source_outside_inbox(tmp_path: Path) -> None:
    manager = ReceiptFileManager(AppConfig(root_folder=tmp_path / "workspace"))
    manager.create_workspace()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7")
    with pytest.raises(ValueError):
        manager.move_to_review(outside)


def test_retention_lists_old_archive_files_and_requires_confirmation(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path)
    archive = ReceiptFileManager(config).create_workspace()["archive"]
    old = archive / "2025" / "01" / "old.pdf"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    now = datetime(2026, 8, 6, tzinfo=UTC)
    old_timestamp = (now - timedelta(days=40)).timestamp()
    os.utime(old, (old_timestamp, old_timestamp))

    service = RetentionService(config)
    candidates = service.candidates_older_than(30, now=now)
    assert [candidate.path for candidate in candidates] == [old]
    with pytest.raises(PermissionError):
        service.delete_candidates(candidates)
    assert service.delete_candidates(candidates, confirmed=True) == 1
    assert not old.exists()


def test_retention_rejects_outside_candidate(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    service = RetentionService(config)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"data")
    candidate = RetentionCandidate(outside, 4, datetime.now(UTC))
    with pytest.raises(ValueError):
        service.delete_candidates([candidate], confirmed=True)


def test_storage_usage_reports_requested_areas(tmp_path: Path) -> None:
    config = AppConfig(root_folder=tmp_path)
    paths = ReceiptFileManager(config).create_workspace()
    (paths["inbox"] / "one.pdf").write_bytes(b"12345")
    (paths["exports"] / "report.csv").write_bytes(b"123")

    report = calculate_storage_usage(config)
    assert report.inbox_bytes == 5
    assert report.exports_bytes == 3
    assert report.total_bytes >= 8
    assert report.disk_capacity_bytes > report.total_bytes
    assert report.disk_free_bytes > 0
    assert 0 <= report.disk_usage_percent < 100
    assert report.as_dict()["inbox"] == 5
    assert path_size(tmp_path / "missing") == 0
