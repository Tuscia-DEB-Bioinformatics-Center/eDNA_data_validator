"""Tests for the .xlsx and .tsv readers."""

from __future__ import annotations

import io

import openpyxl
import pytest

from edna_validator.core import validate_file
from edna_validator.readers import ReadError, read_file, read_tsv

HEADER = ["Sample", "Category", "File_forward", "File_reverse"]


def save(workbook: openpyxl.Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "Pool 1"
    first.append(HEADER)
    first.append(["A 1", "Mare", "/d/a_1.fq.gz", "/d/a_2.fq.gz"])
    first.append([None, None, None, None])
    first.append(["   ", None, " ", None])
    first.append([1.10, "Mare", "/d/b_1.fq.gz", "/d/b_2.fq.gz"])
    first.append(["C", "=B2", "/d/c_1.fq.gz", "/d/c_2.fq.gz"])

    workbook.create_sheet("Vuota")

    reordered = workbook.create_sheet("Pool_1")
    reordered.append(["File_reverse", "Note", " Sample ", "File_forward", "Category", None, None])
    reordered.append(["/d/x_2.fq.gz", "extra", "X", "/d/x_1.fq.gz", "Lago", None, "senza nome"])

    workbook.create_sheet("Solo intestazione").append(HEADER)
    return save(workbook)


def test_multiple_sheets_and_empty_sheet() -> None:
    datasets = read_file(build_workbook(), "tabella.xlsx")
    assert [d.name for d in datasets] == ["Pool 1", "Vuota", "Pool_1", "Solo intestazione"]
    assert datasets[1].columns == [] and datasets[1].rows == []
    assert datasets[3].columns == HEADER and datasets[3].rows == []


def test_blank_rows_are_ignored_and_row_numbers_match_excel() -> None:
    dataset = read_file(build_workbook(), "tabella.xlsx")[0]
    assert [row.number for row in dataset.rows] == [2, 5, 6]
    assert dataset.rows[0].values["Sample"] == "A 1"


def test_numeric_cell_is_rendered_as_text_and_recorded() -> None:
    dataset = read_file(build_workbook(), "tabella.xlsx")[0]
    assert dataset.rows[1].values["Sample"] == "1.1"
    assert [(c.row, c.column, c.kind) for c in dataset.converted] == [(5, "Sample", "numero")]


def test_formula_without_cached_value_is_detected() -> None:
    dataset = read_file(build_workbook(), "tabella.xlsx")[0]
    assert dataset.rows[2].values["Category"] == ""
    assert dataset.formula_cells == {(6, "Category")}


def test_reordered_and_extra_columns() -> None:
    dataset = read_file(build_workbook(), "tabella.xlsx")[2]
    assert dataset.columns == ["File_reverse", "Note", "Sample", "File_forward", "Category"]
    assert dataset.rows[0].values["Sample"] == "X"
    assert dataset.unnamed_columns == 1


def test_workbook_end_to_end() -> None:
    result = validate_file(build_workbook(), "tabella.xlsx", "auto")
    by_name = {sheet.sheet: sheet for sheet in result.sheets}
    assert by_name["Vuota"].status == "empty"
    assert by_name["Solo intestazione"].status == "empty"
    assert {i.code for i in by_name["Vuota"].issues} == {"I05"}

    first = by_name["Pool 1"]
    assert first.pipeline == "eDNA_short"
    assert {i.code for i in first.issues if i.severity == "error"} == {"E13", "E14"}
    assert "dedotta" in next(i for i in first.issues if i.code == "I04").message

    second = by_name["Pool_1"]
    assert second.tsv == (
        "Sample\tCategory\tFile_forward\tFile_reverse\nX\tLago\t/d/x_1.fq.gz\t/d/x_2.fq.gz\n"
    )
    assert (first.tsv_name, second.tsv_name) == ("Pool_1.tsv", "Pool_1_2.tsv")
    assert "I06" in {i.code for i in second.issues}
    assert "I02" in {i.code for i in second.issues}


def test_skip_sheet_and_per_sheet_pipeline() -> None:
    result = validate_file(
        build_workbook(), "tabella.xlsx", "auto", {"Pool 1": "skip", "Pool_1": "eDNA"}
    )
    by_name = {sheet.sheet: sheet for sheet in result.sheets}
    assert by_name["Pool 1"].status == "skipped"
    assert by_name["Pool_1"].pipeline == "eDNA"
    assert by_name["Pool_1"].tsv_name == "Pool_1.tsv"
    with pytest.raises(ValueError, match="Schede non presenti"):
        validate_file(build_workbook(), "tabella.xlsx", "auto", {"Inesistente": "eDNA"})


def test_date_and_integer_cells() -> None:
    import datetime as dt

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    sheet.append(["S1", dt.datetime(2025, 7, 1), "/d/a_1.fq.gz", "/d/a_2.fq.gz"])
    sheet.append(["S2", 7, "/d/b_1.fq.gz", "/d/b_2.fq.gz"])
    result = validate_file(save(workbook), "t.xlsx", "eDNA_short").sheets[0]
    assert [(i.rows, i.value) for i in result.issues if i.code == "W07"] == [
        ([2], "2025-07-01"),
        ([3], "7"),
    ]
    assert result.tsv is not None


def test_tsv_with_bom_crlf_and_blank_lines() -> None:
    data = "﻿Sample\tCategory\tFile\r\n\r\nA\tMare\t/d/a.fq.gz\r\n\t\t\r\n".encode()
    dataset = read_tsv(data, "t")
    assert dataset.columns == ["Sample", "Category", "File"]
    assert [(row.number, row.values["Sample"]) for row in dataset.rows] == [(3, "A")]


def test_tsv_windows_1252_fallback() -> None:
    data = "Sample\tCategory\tFile\nA\tLagò\t/d/a.fq.gz\n".encode("cp1252")
    assert read_tsv(data, "t").rows[0].values["Category"] == "Lagò"


@pytest.mark.parametrize("name", ["t.xls", "t.csv", "t.ods", "t.docx", "tabella"])
def test_unsupported_formats(name: str) -> None:
    with pytest.raises(ReadError):
        read_file(b"x", name)
    result = validate_file(b"x", name)
    assert [issue.code for issue in result.file_issues] == ["E00"]
    assert result.has_errors


def test_corrupt_xlsx_and_utf16_tsv() -> None:
    assert validate_file(b"non un excel", "t.xlsx").file_issues[0].code == "E00"
    assert validate_file("Sample\tFile\n".encode("utf-16"), "t.tsv").file_issues[0].code == "E00"
