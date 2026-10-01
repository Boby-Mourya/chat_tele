from __future__ import annotations

import re


_PRICE_TERMS = r"(?:price|pricing|cost|fee|fees|tuition|discount|offer|payment\s+plan|installments?)"
_PRODUCT_TERMS = r"(?:course|program|programme|batch|certification|certification\s+program|cpa|cma|acca)"
_ACTION_TERMS = r"(?:buy|purchase|enrol|enroll|join|upgrade|admission)"

_PATTERNS = (
    re.compile(rf"\b{_PRICE_TERMS}\b.{{0,48}}\b{_PRODUCT_TERMS}\b", re.IGNORECASE),
    re.compile(rf"\b{_PRODUCT_TERMS}\b.{{0,48}}\b{_PRICE_TERMS}\b", re.IGNORECASE),
    re.compile(rf"\b{_ACTION_TERMS}\b.{{0,48}}\b{_PRODUCT_TERMS}\b", re.IGNORECASE),
    re.compile(rf"\b(?:how\s+much|what\s+does)\b.{{0,48}}\b{_PRODUCT_TERMS}\b.{{0,24}}\b(?:cost|charge)\b", re.IGNORECASE),
)


def detects_education_sales_intent(message: str) -> bool:
    """Conservatively identify Education messages that express purchase/upsell intent.

    This intentionally requires both commercial intent and an education product context
    so academic questions such as "explain price elasticity" do not become sales leads.
    """

    normalized = " ".join(message.strip().split())
    if not normalized:
        return False
    return any(pattern.search(normalized) is not None for pattern in _PATTERNS)
