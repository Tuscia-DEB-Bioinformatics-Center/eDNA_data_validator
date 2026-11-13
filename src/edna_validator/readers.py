"""Input readers: turn the bytes of a .xlsx or .tsv file into cleaned datasets."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from pathlib import PurePath

from .cleaning import cell_to_text, trim
from .models import ConvertedCell, Dataset, Row

_UNSUPPORTED = {
    ".xls": "Il vecchio formato Excel .xls non è supportato: salva il file come .xlsx.",
    ".csv": "Il formato .csv non è supportato: salva il file come .xlsx oppure come .tsv "
    "(testo delimitato da tabulazioni).",
    ".ods": "Il formato .ods non è supportato: salva il file come .xlsx.",
}


class ReadError(Exception):
    """Raised when the input file cannot be read; the message is shown to the user (E00)."""


def read_file(data: bytes, filename: str) -> list[Dataset]:
    """Read an input file into datasets.

    Args:
        data: Raw content of the file.
        filename: Original file name, used to pick the format and name TSV datasets.

    Returns:
        One dataset per sheet (.xlsx) or a single dataset (.tsv).

    Raises:
        ReadError: If the format is not supported or the file cannot be parsed.
    """
    path = PurePath(filename)
    suffix = path.suffix.lower()
    if suffix == ".tsv":
        return [read_tsv(data, path.stem)]
    if suffix == ".xlsx":
        return read_xlsx(data)
    if suffix in _UNSUPPORTED:
        raise ReadError(_UNSUPPORTED[suffix])
    raise ReadError(
        f"Formato '{suffix or filename}' non supportato: sono accettati solo file .xlsx e .tsv."
    )


def read_tsv(data: bytes, name: str) -> Dataset:
    """Read a tab-separated file.

    Args:
        data: Raw content of the file (UTF-8 with or without BOM, or Windows-1252).
        name: Dataset name.

    Returns:
        The cleaned dataset.

    Raises:
        ReadError: If the file is UTF-16 or cannot be parsed.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise ReadError(
            'Il file .tsv è in codifica UTF-16 ("Testo Unicode" di Excel): salvalo come '
            ".xlsx oppure come testo UTF-8 delimitato da tabulazioni."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    try:
        records = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))
    except csv.Error as exc:
        raise ReadError(f"Il file .tsv non è leggibile: {exc}.") from exc
    return _build_dataset(name, enumerate(records, start=1))


def read_xlsx(data: bytes) -> list[Dataset]:
    """Read every worksheet of an Excel workbook.

    Args:
        data: Raw content of the .xlsx file.

    Returns:
        One dataset per worksheet, in workbook order.

    Raises:
        ReadError: If the workbook cannot be opened.
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise ReadError(
            "La libreria openpyxl non è disponibile: impossibile leggere .xlsx."
        ) from exc

    try:
        values_wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        formulas_wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=True)
    except Exception as exc:
        raise ReadError(
            "Il file .xlsx non è leggibile: potrebbe essere danneggiato, protetto da password "
            "o non essere un vero file Excel."
        ) from exc

    datasets: list[Dataset] = []
    try:
        for sheet in values_wb.worksheets:
            sheet.reset_dimensions()
            formula_sheet = formulas_wb[sheet.title]
            formula_sheet.reset_dimensions()
            formulas = {
                (row_number, index)
                for row_number, row in enumerate(formula_sheet.iter_rows(), start=1)
                for index, cell in enumerate(row)
                if cell.data_type == "f"
            }
            rows = (
                (row_number, [cell.value for cell in row])
                for row_number, row in enumerate(sheet.iter_rows(), start=1)
            )
            datasets.append(_build_dataset(sheet.title, rows, formulas))
    except Exception as exc:
        raise ReadError(f"Il file .xlsx non è leggibile: {exc}.") from exc
    finally:
        values_wb.close()
        formulas_wb.close()
    return datasets


def _build_dataset(
    name: str,
    raw_rows: Iterable[tuple[int, list[object]]],
    formulas: set[tuple[int, int]] | None = None,
) -> Dataset:
    """Clean raw rows and assemble a dataset; row 1 is the header."""
    dataset = Dataset(name=name)
    column_index: dict[str, int] = {}
    header: list[str] = []
    unnamed: set[int] = set()
    formulas_by_row: dict[int, set[int]] = {}
    for row_number, index in formulas or ():
        formulas_by_row.setdefault(row_number, set()).add(index)

    for number, cells in raw_rows:
        converted = [cell_to_text(cell) for cell in cells]
        texts = [trim(text) for text, _ in converted]
        if number == 1:
            header = texts
            # A repeated header is ambiguous: its columns are reported and not used.
            for index, column in enumerate(texts):
                if not column:
                    continue
                if texts.count(column) > 1:
                    if column not in dataset.duplicate_columns:
                        dataset.duplicate_columns.append(column)
                    continue
                column_index[column] = index
                dataset.columns.append(column)
            continue

        pending_formulas = {
            index
            for index in formulas_by_row.get(number, ())
            if index >= len(texts) or not texts[index]
        }
        if not any(texts) and not pending_formulas:
            continue

        values = {
            column: texts[index] if index < len(texts) else ""
            for column, index in column_index.items()
        }
        for column, index in column_index.items():
            if index < len(converted) and converted[index][1] and texts[index]:
                dataset.converted.append(
                    ConvertedCell(number, column, converted[index][1], texts[index])
                )
            if index in pending_formulas:
                dataset.formula_cells.add((number, column))
        for index, text in enumerate(texts):
            if text and (index >= len(header) or not header[index]):
                unnamed.add(index)
        dataset.rows.append(Row(number, values))

    dataset.unnamed_columns = len(unnamed)
    return dataset
