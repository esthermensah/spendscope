from decimal import Decimal

from spendscope.categorization.engine import RuleBasedCategorizer
from spendscope.categorization.models import ReceiptContext
from spendscope.categorization.normalization import normalize_item, normalize_merchant
from spendscope.parsing.models import ParsedLineItem


def item(description: str, amount: str = "1.00") -> ParsedLineItem:
    return ParsedLineItem(
        description=description,
        quantity=Decimal("1"),
        unit_price=Decimal(amount),
        line_total=Decimal(amount),
        confidence=0.9,
        source_line=f"{description} {amount}",
    )


def context(merchant: str = "Walmart Store #123") -> ReceiptContext:
    return ReceiptContext(merchant, normalize_merchant(merchant))


def test_item_and_merchant_normalization_is_conservative() -> None:
    assert normalize_merchant("  CAFÉ Company — Store #42 ") == "cafe"
    assert normalize_item("Laundry Detergent (SKU 12-A)") == "laundry detergent"


def test_keyword_rules_split_a_mixed_category_receipt() -> None:
    receipt = RuleBasedCategorizer().categorize_receipt(
        (
            item("Rice", "12.00"),
            item("Chicken", "15.00"),
            item("Shampoo", "8.00"),
            item("Laundry Detergent", "10.00"),
            item("Notebook", "5.00"),
        ),
        context(),
    )

    assert {
        allocation.category_internal_name: allocation.amount for allocation in receipt.allocations
    } == {
        "education": Decimal("5.00"),
        "groceries": Decimal("27.00"),
        "household": Decimal("10.00"),
        "personal_care": Decimal("8.00"),
    }
    assert all(entry.categorization.source == "keyword_rule" for entry in receipt.items)


def test_item_evidence_takes_priority_over_merchant_fallback() -> None:
    categorizer = RuleBasedCategorizer(merchant_category_rules={"walmart": "shopping"})

    result = categorizer.categorize_item(item("Rice"), context("Walmart"))
    fallback = categorizer.categorize_item(item("Unknown 123"), context("Walmart"))

    assert result.category_internal_name == "groceries"
    assert fallback.category_internal_name == "shopping"
    assert fallback.source == "merchant_fallback"
    assert fallback.confidence == 0.60


def test_correction_rule_precedes_built_in_keyword_rule() -> None:
    categorizer = RuleBasedCategorizer(item_rules={"rice": ("rice flour", "education")})

    result = categorizer.categorize_item(item("RICE"), context())

    assert result.category_internal_name == "education"
    assert result.normalized_description == "rice flour"
    assert result.confidence == 1.0
    assert result.source == "correction_rule"


def test_ambiguous_and_unknown_items_remain_unallocated() -> None:
    categorizer = RuleBasedCategorizer(
        keyword_rules={"groceries": frozenset({"bar"}), "shopping": frozenset({"bar"})}
    )

    ambiguous = categorizer.categorize_item(item("Bar"), context())
    unknown = RuleBasedCategorizer().categorize_item(item("ZXQ 9000"), context())

    assert ambiguous.category_internal_name == "unallocated"
    assert ambiguous.source == "ambiguous_keywords"
    assert unknown.category_internal_name == "unallocated"
    assert unknown.confidence == 0.25
