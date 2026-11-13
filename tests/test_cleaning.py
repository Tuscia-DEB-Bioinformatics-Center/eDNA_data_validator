"""Unit tests for trimming, normalisation and cell conversion."""

from __future__ import annotations

import datetime as dt

import pytest

from edna_validator.cleaning import cell_to_text, normalize_sample, trim


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Mare  ", "Mare"),
        ("\tMare\n", "Mare"),
        (" Mare ", "Mare"),
        ("​Mare​", "Mare"),
        ("﻿Sample", "Sample"),
        ("‌‍⁠x\r\n", "x"),
        ("Laghi costieri", "Laghi costieri"),
        ("Laghi costieri", "Laghi costieri"),
        ("  ​ ", ""),
    ],
)
def test_trim(raw: str, expected: str) -> None:
    assert trim(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sab B 2.1/A", "Sab_B_2_1_A"),
        ("Sab B 2.1/", "Sab_B_2_1"),
        ("A - 1", "A_1"),
        ("__x__", "x"),
        ("--", ""),
        ("Lagò 1", "Lag_1"),
        ("Elba_B_1_2", "Elba_B_1_2"),
    ],
)
def test_normalize_sample(raw: str, expected: str) -> None:
    assert normalize_sample(raw) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("", None)),
        ("abc", ("abc", None)),
        (12, ("12", "numero")),
        (12.0, ("12", "numero")),
        (1.10, ("1.1", "numero")),
        (True, ("TRUE", "valore logico")),
        (dt.datetime(2025, 7, 1), ("2025-07-01", "data")),
        (dt.datetime(2025, 7, 1, 9, 30), ("2025-07-01 09:30:00", "data")),
        (dt.date(2025, 7, 1), ("2025-07-01", "data")),
    ],
)
def test_cell_to_text(value: object, expected: tuple[str, str | None]) -> None:
    assert cell_to_text(value) == expected
