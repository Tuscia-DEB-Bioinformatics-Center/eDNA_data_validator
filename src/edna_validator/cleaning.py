"""Cell cleaning: trimming, Sample normalisation and cell-to-text conversion."""

from __future__ import annotations

import datetime as dt
import re

# Spaces, tabs, line breaks, NBSP, zero-width characters and BOM.
TRIM_CHARS = " \t\n\r\v\f ​‌‍⁠﻿"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def trim(value: str) -> str:
    """Remove leading and trailing blank characters from a cell value.

    Args:
        value: Raw text of the cell.

    Returns:
        The text without leading/trailing spaces, tabs, line breaks, NBSP,
        zero-width characters and BOM.
    """
    return value.strip(TRIM_CHARS)


def normalize_sample(value: str) -> str:
    """Normalise a sample (or sheet) name to ASCII letters, digits and underscores.

    Args:
        value: Trimmed name.

    Returns:
        The name with every run of non-alphanumeric ASCII characters replaced by a
        single underscore and without leading/trailing underscores.
    """
    return _NON_ALNUM.sub("_", value).strip("_")


def cell_to_text(value: object) -> tuple[str, str | None]:
    """Convert a raw cell value to text.

    Args:
        value: Value as returned by the reader (str, number, date, bool or None).

    Returns:
        A tuple ``(text, kind)``. ``kind`` is None for text and empty cells, otherwise
        an Italian label of the original type ("numero", "data", "valore logico").
    """
    if value is None:
        return "", None
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), "valore logico"
    if isinstance(value, int):
        return str(value), "numero"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value)), "numero"
        return repr(value), "numero"
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0, 0):
            return value.date().isoformat(), "data"
        return value.isoformat(sep=" "), "data"
    if isinstance(value, dt.date | dt.time):
        return value.isoformat(), "data"
    return str(value), "valore non testuale"
