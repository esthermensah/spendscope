from datetime import date
from pathlib import Path

from PIL import Image
from sqlalchemy import Engine

from spendscope.config import AppConfig
from spendscope.database.connection import session_scope
from spendscope.database.repositories import ProcessedFileRepository
from spendscope.processing.file_manager import ReceiptFileManager
from spendscope.processing.pipeline import IntakeStatus, StoragePipeline


def test_storage_pipeline_registers_duplicates_and_archives(
    tmp_path: Path, database_engine: Engine
) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    paths = ReceiptFileManager(config).create_workspace()
    receipt = paths["inbox"] / "receipt.jpg"
    Image.new("RGB", (2800, 1800), "white").save(receipt)
    original_bytes = receipt.read_bytes()

    with session_scope(database_engine) as session:
        pipeline = StoragePipeline(config, session)
        first = pipeline.scan_and_register()
        assert first[0].status is IntakeStatus.ACCEPTED
        record_id = first[0].record_id
        assert record_id is not None
        resumed = pipeline.scan_and_register()
        assert resumed[0].status is IntakeStatus.RESUMED
        assert resumed[0].record_id == record_id
        archived = pipeline.archive_confirmed(record_id, date(2026, 8, 6))
        assert archived is not None and archived.exists()

    receipt.write_bytes(original_bytes)
    with session_scope(database_engine) as session:
        result = StoragePipeline(config, session).scan_and_register()
        assert result[0].status is IntakeStatus.DUPLICATE
        assert receipt.exists()


def test_storage_pipeline_tracks_review_and_invalid_files(
    tmp_path: Path, database_engine: Engine
) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    paths = ReceiptFileManager(config).create_workspace()
    valid = paths["inbox"] / "review.pdf"
    valid.write_bytes(b"%PDF-1.7 review")
    invalid = paths["inbox"] / "bad.txt"
    invalid.write_text("bad", encoding="utf-8")

    with session_scope(database_engine) as session:
        pipeline = StoragePipeline(config, session)
        results = pipeline.scan_and_register()
        statuses = {result.path.name: result.status for result in results}
        assert statuses == {"bad.txt": IntakeStatus.INVALID, "review.pdf": IntakeStatus.ACCEPTED}
        review_record = next(result for result in results if result.status is IntakeStatus.ACCEPTED)
        destination = pipeline.require_review(review_record.record_id or 0)
        assert destination.parent == paths["needs_review"]
        record = ProcessedFileRepository(session).get(review_record.record_id or 0)
        assert record is not None and record.processing_status == "needs_review"
