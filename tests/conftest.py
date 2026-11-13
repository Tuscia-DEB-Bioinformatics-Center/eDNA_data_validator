"""Shared fixtures: the real valid table and broken variants derived from it."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pytest

from edna_validator.core import validate_file
from edna_validator.models import SheetResult

DATA_FILE = Path(__file__).parent / "data" / "EUKA_lug25.tsv"


class Table:
    """Editable copy of a table, addressed by Excel row number and column name."""

    def __init__(self, header: list[str], rows: list[list[object]]) -> None:
        self.header = header
        self.rows = rows

    def get(self, row: int, column: str) -> object:
        """Return the value at an Excel row (2 = first data row)."""
        return self.rows[row - 2][self.header.index(column)]

    def set(self, row: int, column: str, value: object) -> None:
        """Set the value at an Excel row (2 = first data row)."""
        self.rows[row - 2][self.header.index(column)] = value

    def rename_column(self, old: str, new: str) -> None:
        """Rename a header."""
        self.header[self.header.index(old)] = new

    def drop_column(self, column: str) -> None:
        """Remove a column with its values."""
        index = self.header.index(column)
        del self.header[index]
        for row in self.rows:
            del row[index]

    def to_short(self) -> None:
        """Turn the eDNA table into a valid eDNA_short one (one file pair per sample)."""
        self.drop_column("Forward")
        self.drop_column("Reverse")
        for number in range(2, len(self.rows) + 2):
            self.set(number, "File_forward", f"/data/run/sample{number}_1.fq.gz")
            self.set(number, "File_reverse", f"/data/run/sample{number}_2.fq.gz")

    def to_tsv(self) -> bytes:
        """Serialise as TSV bytes (cells with tabs or line breaks are quoted)."""
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        writer.writerow(self.header)
        writer.writerows(self.rows)
        return buffer.getvalue().encode("utf-8")

    def to_xlsx(self, sheet: str = "Foglio1") -> bytes:
        """Serialise as a one-sheet workbook, keeping non-text values as they are."""
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = sheet
        worksheet.append(self.header)
        for row in self.rows:
            worksheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def validate(self, pipeline: str = "eDNA", fmt: str = "tsv") -> SheetResult:
        """Validate the table and return the result of its only sheet."""
        if fmt == "xlsx":
            result = validate_file(self.to_xlsx(), "tabella.xlsx", pipeline)
        else:
            result = validate_file(self.to_tsv(), "tabella.tsv", pipeline)
        assert len(result.sheets) == 1
        return result.sheets[0]


def load_valid_table() -> Table:
    """Load the real valid table as an editable copy."""
    lines = DATA_FILE.read_text(encoding="utf-8").splitlines()
    cells = [line.split("\t") for line in lines if line]
    return Table(cells[0], [list(row) for row in cells[1:]])


@pytest.fixture
def valid_bytes() -> bytes:
    """Bytes of the real valid file."""
    return DATA_FILE.read_bytes()


@pytest.fixture
def table() -> Table:
    """Editable copy of the real valid table."""
    return load_valid_table()


@dataclass
class Variant:
    """A broken variant of the valid table and the issue it must produce."""

    code: str
    mutate: Callable[[Table], None]
    rows: list[int]
    column: str | None
    pipeline: str = "eDNA"
    fmt: str = "tsv"


def _e11(t: Table) -> None:
    t.to_short()
    t.set(3, "File_reverse", t.get(2, "File_forward"))


def _e10(t: Table) -> None:
    t.set(3, "Forward", str(t.get(2, "Forward")).upper())
    t.set(3, "Reverse", t.get(2, "Reverse"))


VARIANTS = [
    Variant("E01", lambda t: t.rename_column("Sample", "sample"), [1], "Sample"),
    Variant("E02", lambda t: t.set(5, "File_forward", ""), [5], "File_forward"),
    Variant("E03", lambda t: t.set(4, "Sample", "--"), [4], "Sample"),
    Variant("E04", lambda t: t.set(3, "Sample", "Civ-B 2.2"), [2, 3], "Sample"),
    Variant("E05", lambda t: t.set(6, "File_reverse", "dati/x_2.fq.gz"), [6], "File_reverse"),
    Variant("E06", lambda t: t.set(7, "File_forward", "/a b/x_1.fq.gz"), [7], "File_forward"),
    Variant("E07", lambda t: t.set(8, "File_forward", "/a/x_1.FASTQ"), [8], "File_forward"),
    Variant(
        "E08", lambda t: t.set(9, "File_reverse", t.get(9, "File_forward")), [9], "File_reverse"
    ),
    Variant("E09", lambda t: t.set(10, "Forward", "ACGTXACG"), [10], "Forward"),
    Variant("E10", _e10, [2, 3], None),
    Variant("E11", _e11, [2, 3], "File_forward, File_reverse", pipeline="eDNA_short"),
    Variant("E12", lambda t: t.set(4, "Category", "Laghi\tcostieri"), [4], "Category"),
    Variant("E13", lambda t: t.set(5, "Sample", 1.10), [5], "Sample", fmt="xlsx"),
    Variant("E14", lambda t: t.set(5, "Forward", "=A1"), [5], "Forward", fmt="xlsx"),
    Variant("W01", lambda t: t.set(5, "Category", ""), [5], "Category"),
    Variant(
        "W02",
        lambda t: t.set(4, "Category", "Laghi Costieri"),
        [4, 12, 16, 17, 53, 54],
        "Category",
    ),
    Variant("W03", lambda t: t.set(2, "Sample", "civ b 2.1"), [2, 15], "Sample"),
    Variant("W04", lambda t: t.set(6, "File_forward", "/a-b/x_1.fq.gz"), [6], "File_forward"),
    Variant("W05", lambda t: t.set(6, "File_forward", "/a/è_1.fq.gz"), [6], "File_forward"),
    Variant("W06", lambda t: t.set(6, "File_forward", "/a/x_1.fq.bz2"), [6], "File_forward"),
    Variant("W07", lambda t: t.set(5, "Category", 12), [5], "Category", fmt="xlsx"),
]


@pytest.fixture(params=VARIANTS, ids=[variant.code for variant in VARIANTS])
def variant(request: pytest.FixtureRequest) -> Variant:
    """One broken variant per rule code."""
    return request.param
