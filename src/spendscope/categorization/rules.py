"""Built-in category dictionaries used by the local rules engine."""

from __future__ import annotations

DEFAULT_ITEM_KEYWORDS: dict[str, frozenset[str]] = {
    "groceries": frozenset(
        {
            "apple",
            "banana",
            "bread",
            "chicken",
            "egg",
            "flour",
            "fruit",
            "milk",
            "rice",
            "vegetable",
            "water",
        }
    ),
    "eating_out": frozenset(
        {"burger", "cafe", "coffee", "meal", "pizza", "restaurant", "sandwich"}
    ),
    "transportation": frozenset(
        {"bus", "fare", "fuel", "gasoline", "parking", "taxi", "train", "uber"}
    ),
    "housing": frozenset({"mortgage", "rent"}),
    "utilities": frozenset(
        {"electricity", "internet", "mobile plan", "natural gas", "phone bill", "water bill"}
    ),
    "household": frozenset(
        {"cleaner", "detergent", "dish soap", "laundry", "paper towel", "trash bag"}
    ),
    "personal_care": frozenset(
        {"conditioner", "cosmetic", "deodorant", "lotion", "shampoo", "toothpaste"}
    ),
    "healthcare": frozenset(
        {"clinic", "medicine", "pharmacy", "prescription", "tablet", "vitamin"}
    ),
    "education": frozenset(
        {"book", "course", "notebook", "pencil", "school", "textbook", "tuition"}
    ),
    "shopping": frozenset({"clothing", "dress", "jacket", "shoe", "shirt"}),
    "entertainment": frozenset({"cinema", "game", "movie", "museum", "theater"}),
    "travel": frozenset({"airfare", "flight", "hotel", "luggage"}),
    "subscriptions": frozenset(
        {"annual renewal", "membership", "monthly", "monthly plan", "recurring", "subscription"}
    ),
    "gifts_donations": frozenset({"charity", "donation", "gift"}),
    "one_time_purchases": frozenset(
        {
            "appliance",
            "camera",
            "computer",
            "couch",
            "desk",
            "furniture",
            "laptop",
            "mattress",
            "mirror",
            "monitor",
            "printer",
            "refrigerator",
            "sofa",
            "table",
            "television",
            "tv",
        }
    ),
}
