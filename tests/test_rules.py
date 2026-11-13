"""Tests for the validation rules, driven by broken variants of the valid table."""

from __future__ import annotations

import pytest

from conftest import Table, Variant
from edna_validator.models import SheetResult
from edna_validator.rules import _extension_problem
from edna_validator.schema import CODE_TITLES


def codes(result: SheetResult, severity: str | None = None) -> set[str]:
    return {i.code for i in result.issues if severity is None or i.severity == severity}


def find(result: SheetResult, code: str) -> list:
    return [issue for issue in result.issues if issue.code == code]


def test_variant_reports_code_rows_and_column(table: Table, variant: Variant) -> None:
    variant.mutate(table)
    result = table.validate(variant.pipeline, variant.fmt)
    matches = [
        issue
        for issue in find(result, variant.code)
        if issue.rows == variant.rows and issue.column == variant.column
    ]
    assert matches, [(i.code, i.rows, i.column) for i in result.issues if i.severity != "info"]
    assert matches[0].severity == {"E": "error", "W": "warning"}[variant.code[0]]
    if variant.code.startswith("E"):
        assert result.tsv is None
    assert variant.code in CODE_TITLES


def test_every_rule_code_has_a_variant() -> None:
    from conftest import VARIANTS

    covered = {variant.code for variant in VARIANTS}
    expected = {code for code in CODE_TITLES if code[0] in "EW"} - {"E00"}
    assert covered == expected


def test_short_variant_is_valid(table: Table) -> None:
    table.to_short()
    result = table.validate("eDNA_short")
    assert not codes(result, "error")
    assert result.tsv is not None


def test_e01_suggests_similar_column(table: Table) -> None:
    table.rename_column("File_forward", "File forward")
    issue = find(table.validate(), "E01")[0]
    assert issue.column == "File_forward"
    assert "'File forward'" in issue.message


def test_e01_runs_only_independent_checks(table: Table) -> None:
    table.drop_column("File_reverse")
    table.set(3, "Sample", "Civ B 2.2")
    result = table.validate()
    assert codes(result, "error") == {"E01", "E04"}


def test_e01_duplicate_header(table: Table) -> None:
    table.header.append("Sample")
    for row in table.rows:
        row.append("x")
    issue = find(table.validate(), "E01")[0]
    assert "più volte" in issue.message


def test_e01_duplicate_header_does_not_cascade(table: Table) -> None:
    index = table.header.index("File_forward")
    table.header.insert(index, "File_forward")
    for row in table.rows:
        row.insert(index, "A1")
    result = table.validate("auto")
    assert result.pipeline == "eDNA"
    assert [(i.code, i.column) for i in result.issues if i.severity == "error"] == [
        ("E01", "File_forward")
    ]
    assert not codes(result, "warning") - {"W03"}


def test_misspelled_header_keeps_the_intended_pipeline(table: Table) -> None:
    table.rename_column("Forward", "Fowrard ")
    result = table.validate("auto")
    assert result.pipeline == "eDNA"
    errors = [i for i in result.issues if i.severity == "error"]
    assert [(i.code, i.column, i.value) for i in errors] == [("E01", "Forward", "Fowrard")]


def test_e02_does_not_cascade(table: Table) -> None:
    table.set(5, "File_forward", "   ")
    table.set(6, "Forward", "")
    result = table.validate()
    assert codes(result, "error") == {"E02"}
    assert {(i.column, tuple(i.rows)) for i in find(result, "E02")} == {
        ("File_forward", (5,)),
        ("Forward", (6,)),
    }


def test_e04_shows_original_values(table: Table) -> None:
    table.set(3, "Sample", "Civ.B.2.2")
    issue = find(table.validate(), "E04")[0]
    assert "'Civ B 2.2' (riga 2)" in issue.message
    assert "'Civ.B.2.2' (riga 3)" in issue.message


def test_e09_reports_character_and_position(table: Table) -> None:
    table.set(10, "Reverse", "acgtnZ")
    issue = find(table.validate(), "E09")[0]
    assert "'Z' in posizione 6" in issue.message


def test_e10_not_raised_for_shared_files(table: Table) -> None:
    assert "E10" not in codes(table.validate())


def test_e11_same_column(table: Table) -> None:
    table.to_short()
    table.set(5, "File_forward", table.get(2, "File_forward"))
    issue = find(table.validate("eDNA_short"), "E11")[0]
    assert issue.rows == [2, 5]
    assert issue.column == "File_forward"


def test_single_end_pipelines(table: Table) -> None:
    table.rename_column("File_forward", "File")
    table.drop_column("File_reverse")
    result = table.validate("eDNA_single")
    assert not codes(result, "error")
    assert result.tsv.splitlines()[0] == "Sample\tCategory\tFile\tForward\tReverse"

    table.set(3, "Forward", table.get(2, "Forward"))
    table.set(3, "Reverse", table.get(2, "Reverse"))
    assert find(table.validate("eDNA_single"), "E10")[0].rows == [2, 3]
    assert find(table.validate("eDNA_single_short"), "E11")


def test_w01_assigns_default_category(table: Table) -> None:
    table.set(5, "Category", "")
    result = table.validate()
    assert result.tsv.splitlines()[4].split("\t")[1] == "Uncategorized"
    assert "Uncategorized: 1" in find(result, "I01")[0].message


def test_w02_levels(table: Table) -> None:
    table.set(4, "Category", "LaghiCostieri")
    table.set(5, "Category", "Laghi costierii")
    issues = find(table.validate(), "W02")
    values = {issue.value for issue in issues}
    assert "Laghi costieri / LaghiCostieri" in values or "LaghiCostieri / Laghi costieri" in values
    assert any("Laghi costierii" in value for value in values)
    assert not any("Mare" in value for value in values)


def test_w05_excludes_hyphen_and_space(table: Table) -> None:
    table.set(6, "File_forward", "/a-b c/x_1.fq.gz")
    result = table.validate()
    assert "W05" not in codes(result)
    assert {"W04", "E06"} <= codes(result)


def test_w05_allows_plus_sign(table: Table) -> None:
    table.set(6, "File_forward", "/a/EUKA+16S/x_1.fq.gz")
    assert "W05" not in codes(table.validate())


def test_w05_reports_character_and_position(table: Table) -> None:
    table.set(6, "File_forward", "/a/x#1.fq.gz")
    assert "'#' in posizione 5" in find(table.validate(), "W05")[0].message


@pytest.mark.parametrize(
    ("path", "fragment"),
    [
        ("/a/x.fq.gz", None),
        ("/a/x.fastq.gz", None),
        ("/a/x.fq", None),
        ("/a/x.FQ.GZ", "maiuscolo"),
        ("/a/x.fastq.Gz", "maiuscolo"),
        ("/a/x.fq.bz2", ".bz2"),
        ("/a/x.fastq.xz", ".xz"),
        ("/a/x.fq.zst", ".zst"),
        ("/a/x.zip", ".zip"),
        ("/a/x.fq.gzip", "non standard"),
        ("/a/x.gz", "non standard"),
        ("/a/x.txt", "non è riconosciuta"),
        ("/a/x", "non è riconosciuta"),
    ],
)
def test_w06_messages(path: str, fragment: str | None) -> None:
    problem = _extension_problem(path)
    if fragment is None:
        assert problem is None
    else:
        assert fragment in problem


def test_e07_is_not_also_w06(table: Table) -> None:
    table.set(8, "File_forward", "/a/x_1.fq")
    result = table.validate()
    assert "E07" in codes(result)
    assert "W06" not in codes(result)


def test_i02_extra_columns(table: Table) -> None:
    table.header.append("Note")
    for row in table.rows:
        row.append("x")
    result = table.validate()
    assert "Note" in find(result, "I02")[0].message
    assert not codes(result, "error")
    assert "Note" not in result.tsv


def test_does_not_stop_at_first_error(table: Table) -> None:
    table.set(2, "File_forward", "")
    table.set(3, "Sample", "--")
    table.set(5, "Sample", "Ast-1.2 ")
    table.set(6, "Sample", "Ast 1 2")
    table.set(7, "File_forward", "relativo/x 1.fastq")
    table.set(8, "File_reverse", table.get(8, "File_forward"))
    table.set(9, "Forward", "ACGU")
    table.set(10, "Category", "")
    result = table.validate()
    assert {"E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09"} <= codes(result, "error")
    assert {"W01", "W03"} <= codes(result, "warning")
    assert result.tsv is None
