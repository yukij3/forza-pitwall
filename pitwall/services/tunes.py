"""Tune versioning helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pitwall.tune.settings import SETTINGS

_ORDER = {s.key: i for i, s in enumerate(SETTINGS)}


def diff_values(old: Mapping[str, float], new: Mapping[str, float]) -> list[dict[str, Any]]:
    """Settings whose value differs, in tuning-menu order.

    Returns ``[{"setting", "from", "to"}]``; ``from``/``to`` is ``None`` when the
    setting is missing on that side.
    """
    keys = sorted(set(old) | set(new), key=lambda k: (_ORDER.get(k, len(_ORDER)), k))
    return [
        {"setting": key, "from": old.get(key), "to": new.get(key)}
        for key in keys
        if old.get(key) != new.get(key)
    ]
