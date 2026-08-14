from __future__ import annotations

from datetime import date
from pathlib import Path

from spendscope.app import initialize_configured_workspace
from spendscope.config import AppConfig, save_config
from spendscope.domain.models import (
    ManualExpenseDraft,
    ReceiptCorrectionDraft,
    ReceiptItemCorrection,
)
from spendscope.ui.controller import DesktopController


def test_confirmed_expense_can_be_recategorized_and_queued(tmp_path: Path) -> None:
    config = initialize_configured_workspace(AppConfig(root_folder=tmp_path / "workspace"))
    config_path = tmp_path / "settings.json"
    save_config(config, config_path)
    controller = DesktopController(config, config_path)
    try:
        controller.create_manual(
            ManualExpenseDraft(
                transaction_date=date(2026, 8, 13),
                description="Online order",
                category_internal_name="unallocated",
                amount_minor=6420,
                currency="USD",
                merchant="EXAMPLE SHOP",
            )
        )
        receipt_id = controller.dashboard(date(2026, 8, 13)).recent_receipts[0][0]
        receipt = controller.confirmed_receipt(receipt_id)

        controller.update_confirmed_receipt(
            ReceiptCorrectionDraft(
                receipt_id=receipt_id,
                merchant=receipt.merchant,
                transaction_date=receipt.transaction_date,
                subtotal_minor=6420,
                final_total_minor=6420,
                items=[
                    ReceiptItemCorrection(
                        id=receipt.items[0].id,
                        description="Online order",
                        line_total_minor=6420,
                        category_internal_name="shopping",
                    )
                ],
            )
        )

        snapshot = controller.dashboard(date(2026, 8, 13))
        assert snapshot.category_spending == (("Shopping", 6420),)
        assert snapshot.pending_sync == 1
    finally:
        controller.close()
