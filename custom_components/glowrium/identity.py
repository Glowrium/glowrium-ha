"""Stable identities shared by local and account-backed devices."""

from __future__ import annotations

import re

from .const import MODEL_C017, MODEL_C045


def normalize_mac(value: str | None) -> str | None:
    """Accept a real six-byte MAC, never an arbitrary platform address."""
    if not isinstance(value, str):
        return None
    compact = re.sub(r"[:-]", "", value).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        return None
    if compact in ("000000000000", "ffffffffffff"):
        return None
    return compact


def hardware_key(mac: str | None, product: str) -> str | None:
    """The protocol MAC and model identify one physical light."""
    normalized = normalize_mac(mac)
    if normalized is None or product not in (MODEL_C017, MODEL_C045):
        return None
    return f"{product}:{normalized}"
