"""Tests of the server cross-check, using a fake reads folder built in a temporary directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import DATA_FILE
from edna_validator.__main__ import main
from edna_validator.readers import read_tsv
from edna_validator.server_check import check_tsv, expand_targets, server_to_local

# Placeholder root used by the test data; the fake reads folder mirrors it under a temp dir.
PREFIX = "/archive/eDNA_project/raw_data/YYYY_MM_DD/SampleName/RUN_0001"


def _table_paths() -> list[str]:
    """Return the distinct FASTQ paths written in the valid example table."""
    dataset = read_tsv(DATA_FILE.read_bytes(), "valid")
    paths: list[str] = []
    for row in dataset.rows:
        for column in ("File_forward", "File_reverse"):
            if row.values[column] not in paths:
                paths.append(row.values[column])
    return paths


def _create_files(root: Path, paths: list[str], prefix: str = PREFIX) -> None:
    """Create empty files under ``root`` for every path, relative to ``prefix``."""
    for path in paths:
        local = server_to_local(path, root, prefix)
        assert local is not None
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(b"")


@pytest.fixture
def reads_root(tmp_path: Path) -> Path:
    """Local folder with every file that the valid example table refers to."""
    root = tmp_path / "reads"
    root.mkdir()
    _create_files(root, _table_paths())
    return root


def test_example_table_has_paths() -> None:
    assert _table_paths(), "the valid example table must contain FASTQ paths"
    assert all(path.startswith(PREFIX + "/") for path in _table_paths())


def test_all_files_present_gives_no_issues(reads_root: Path) -> None:
    issues, checked = check_tsv(DATA_FILE.read_bytes(), "tabella.tsv", reads_root, PREFIX)
    assert issues == []
    assert checked == len(_table_paths())


def test_missing_file_is_e18_with_row(reads_root: Path) -> None:
    dataset = read_tsv(DATA_FILE.read_bytes(), "valid")
    row = dataset.rows[0]
    missing = row.values["File_forward"]
    server_to_local(missing, reads_root, PREFIX).unlink()  # type: ignore[union-attr]

    issues, _ = check_tsv(DATA_FILE.read_bytes(), "tabella.tsv", reads_root, PREFIX)

    codes = {issue.code for issue in issues}
    assert codes == {"E18"}
    e18 = [issue for issue in issues if issue.value == missing]
    assert len(e18) == 1
    assert e18[0].column == "File_forward"
    assert row.number in e18[0].rows


def test_path_outside_prefix_is_e19(reads_root: Path) -> None:
    issues, checked = check_tsv(DATA_FILE.read_bytes(), "tabella.tsv", reads_root, "/altra/radice")
    assert checked > 0
    assert issues and {issue.code for issue in issues} == {"E19"}


def test_without_prefix_whole_path_is_searched(tmp_path: Path) -> None:
    root = tmp_path / "reads"
    root.mkdir()
    _create_files(root, _table_paths(), prefix="")

    issues, _ = check_tsv(DATA_FILE.read_bytes(), "tabella.tsv", root, "")

    assert issues == []


def test_server_to_local_maps_prefix_and_rejects_others(tmp_path: Path) -> None:
    local = server_to_local(f"{PREFIX}/a/x_1.fq.gz", tmp_path, PREFIX)
    assert local == tmp_path / "a" / "x_1.fq.gz"
    assert server_to_local(f"{PREFIX}_altro/x.fq.gz", tmp_path, PREFIX) is None
    assert server_to_local("/altro/x.fq.gz", tmp_path, PREFIX) is None


def test_expand_targets_accepts_folder_pattern_and_file(tmp_path: Path) -> None:
    (tmp_path / "a.tsv").write_bytes(b"x")
    (tmp_path / "b.tsv").write_bytes(b"x")
    (tmp_path / "note.txt").write_bytes(b"x")

    assert [p.name for p in expand_targets([str(tmp_path)])] == ["a.tsv", "b.tsv"]
    assert [p.name for p in expand_targets([str(tmp_path / "*.tsv")])] == ["a.tsv", "b.tsv"]
    assert [p.name for p in expand_targets([str(tmp_path / "a.tsv")])] == ["a.tsv"]


def test_expand_targets_rejects_missing_or_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        expand_targets([str(tmp_path / "non_esiste.tsv")])
    with pytest.raises(ValueError):
        expand_targets([str(tmp_path)])


def test_command_line_exit_codes_and_report(tmp_path: Path, reads_root: Path) -> None:
    table = tmp_path / "out" / "tabella.tsv"
    table.parent.mkdir()
    table.write_bytes(DATA_FILE.read_bytes())
    args = ["controllo-server", str(table), "--radice", str(reads_root), "--prefisso", PREFIX]

    assert main(args) == 0
    report = table.parent / "controllo_server_report.txt"
    assert report.is_file()
    assert "tutti i file" in report.read_text(encoding="utf-8")

    first = _table_paths()[0]
    server_to_local(first, reads_root, PREFIX).unlink()  # type: ignore[union-attr]
    assert main(args) == 1
    assert "E18" in report.read_text(encoding="utf-8")


def test_command_line_unreachable_root_returns_2(tmp_path: Path) -> None:
    table = tmp_path / "tabella.tsv"
    table.write_bytes(DATA_FILE.read_bytes())
    code = main(["controllo-server", str(table), "--radice", str(tmp_path / "non_raggiungibile")])
    assert code == 2


def test_validator_command_line_still_works() -> None:
    assert main([str(DATA_FILE), "--pipeline", "eDNA"]) == 0
