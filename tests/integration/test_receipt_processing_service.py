from pathlib import Path
from typing import cast

from PIL import Image
from sqlalchemy import Engine, select

from spendscope.categorization.memory import CorrectionMemory
from spendscope.config import AppConfig
from spendscope.database.connection import session_scope
from spendscope.database.repositories import CategoryRepository
from spendscope.database.schema import ProcessedFileRecord, ReceiptRecord, ReviewCaseRecord
from spendscope.extraction.base import ExtractionMethod, ExtractionResult
from spendscope.extraction.receipt_extractor import ReceiptTextExtractor
from spendscope.processing.pipeline import StoragePipeline
from spendscope.services.processing import ReceiptProcessingService

CONFIRMED_TEXT = """LOCAL MARKET
Receipt # A-100
Date: 2026-08-05
Currency: USD
LQ DTRG 10.00
RST CHKN 15.00
Subtotal 25.00
Discount 0.50
Tax 2.00
Tip 1.00
TOTAL 27.50
"""

REVIEW_TEXT = """LOCAL MARKET
Date: 2026-08-05
Currency: USD
Mystery Product 5.00
Subtotal 5.00
TOTAL 5.00
"""

MOBILE_ORDER_TEXT = """ONLINE SHOP
Delivery Aug 10-18
125 Example Avenue Apt 4
Jamie Rivera 5550100
Products (11 items)
Order Information
Total $64.20 >
Order Number ORDER-ABC-100
"""


class StaticExtractor:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract(self, path: Path) -> ExtractionResult:
        return ExtractionResult(
            self.text,
            ExtractionMethod.IMAGE_OCR,
            0.98,
            source_path=path,
        )


def inbox_image(config: AppConfig, name: str = "receipt.jpg") -> Path:
    inbox = config.directory_paths()["inbox"]
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    Image.new("RGB", (40, 40), "white").save(path, format="JPEG")
    return path


def test_processing_service_confirms_archives_and_queues_high_confidence_receipt(
    database_engine: Engine, tmp_path: Path
) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    source = inbox_image(config)
    with session_scope(database_engine) as session:
        CategoryRepository(session).seed_defaults()
        memory = CorrectionMemory(session)
        memory.remember_item("LQ DTRG", "Laundry Detergent", "household")
        memory.remember_item("RST CHKN", "Roast Chicken", "groceries")
        intake = StoragePipeline(config, session).scan_and_register()[0]
        assert intake.record_id is not None

        result = ReceiptProcessingService(
            config,
            session,
            cast(ReceiptTextExtractor, StaticExtractor(CONFIRMED_TEXT)),
        ).process(source, intake.record_id)

        receipt = session.get(ReceiptRecord, result.receipt_id)
        file_record = session.get(ProcessedFileRecord, intake.record_id)
        assert result.status == "high"
        assert receipt is not None and receipt.processing_status == "confirmed"
        assert receipt.reconciliation_status == "balanced"
        assert {item.category.internal_name for item in receipt.line_items} == {
            "groceries",
            "household",
        }
        assert file_record is not None and file_record.processing_status == "archived"
        assert file_record.archive_path is not None and Path(file_record.archive_path).exists()
        assert not source.exists()


def test_processing_service_saves_and_moves_low_confidence_receipt_for_review(
    database_engine: Engine, tmp_path: Path
) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    source = inbox_image(config, "unknown.jpg")
    with session_scope(database_engine) as session:
        intake = StoragePipeline(config, session).scan_and_register()[0]
        assert intake.record_id is not None

        result = ReceiptProcessingService(
            config,
            session,
            cast(ReceiptTextExtractor, StaticExtractor(REVIEW_TEXT)),
        ).process(source, intake.record_id)

        receipt = session.get(ReceiptRecord, result.receipt_id)
        review_case = session.scalar(
            select(ReviewCaseRecord).where(ReviewCaseRecord.receipt_id == result.receipt_id)
        )
        file_record = session.get(ProcessedFileRecord, intake.record_id)
        assert result.status == "low"
        assert receipt is not None and receipt.review_status == "required"
        assert receipt.line_items[0].category.internal_name == "unallocated"
        assert review_case is not None and review_case.status == "open"
        assert file_record is not None and file_record.processing_status == "needs_review"
        assert file_record.archive_path is not None and Path(file_record.archive_path).exists()


def test_mobile_order_without_visible_prices_uses_one_unitemized_fallback(
    database_engine: Engine, tmp_path: Path
) -> None:
    config = AppConfig(root_folder=tmp_path / "workspace")
    source = inbox_image(config, "mobile-order.jpg")
    with session_scope(database_engine) as session:
        intake = StoragePipeline(config, session).scan_and_register()[0]
        assert intake.record_id is not None

        result = ReceiptProcessingService(
            config,
            session,
            cast(ReceiptTextExtractor, StaticExtractor(MOBILE_ORDER_TEXT)),
        ).process(source, intake.record_id)

        receipt = session.get(ReceiptRecord, result.receipt_id)
        assert result.status == "low"
        assert receipt is not None
        assert receipt.subtotal_minor == 6420
        assert len(receipt.line_items) == 1
        assert receipt.line_items[0].description_original == "Unitemized purchase"
        assert receipt.line_items[0].line_total_minor == 6420
        assert receipt.raw_extracted_text_path is None
        assert "extracted_text" not in config.directory_paths()
