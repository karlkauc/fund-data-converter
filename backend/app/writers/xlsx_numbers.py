"""Full precision for numbers in XLSX files written with openpyxl.

openpyxl writes every number with ``"%.16g"``, which drops the 17th significant digit a double may
need (``1.8931484249581674`` becomes ``1.893148424958167``). ``repr`` gives the shortest string that
reads back as the same double.
"""

from __future__ import annotations

import math


def full_precision_floats() -> None:
    """Make openpyxl's cell writer serialise floats with ``repr`` (idempotent)."""
    from openpyxl.cell import _writer

    original = _writer.safe_string
    if getattr(original, "full_precision", False):
        return

    def safe_string(value):
        if type(value) is float and math.isfinite(value):
            return repr(value)
        return original(value)

    safe_string.full_precision = True
    _writer.safe_string = safe_string
