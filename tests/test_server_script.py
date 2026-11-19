"""Tests for the standalone Bash script that checks FASTQ paths on the server."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "web" / "controllo_server.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the script runs on Linux servers; Windows paths are not POSIX paths",
)

HEADER = "Sample\tCategory\tFile_forward\tFile_reverse\n"


def run(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the script and capture its output."""
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def reads(tmp_path: Path) -> Path:
    """A reads folder with two existing files, in a folder whose name has a space."""
    folder = tmp_path / "reads" / "run 1"
    folder.mkdir(parents=True)
    (folder / "a_1.fq.gz").touch()
    (folder / "a_2.fq.gz").touch()
    return tmp_path / "reads"


def test_all_files_present(reads: Path, tmp_path: Path) -> None:
    pair = f"{reads}/run 1/a_1.fq.gz\t{reads}/run 1/a_2.fq.gz"
    (tmp_path / "ok.tsv").write_text(f"{HEADER}S1\tMare\t{pair}\nS2\tMare\t{pair}\n")
    result = run(cwd=tmp_path)
    assert result.returncode == 0
    assert "ok.tsv - OK: tutti i file (2) sono presenti sul server." in result.stdout
    assert "RIEPILOGO: 1 tabella controllata, 1 OK, 0 con problemi." in result.stdout


def test_missing_and_relative_paths(reads: Path, tmp_path: Path) -> None:
    ok = f"{reads}/run 1/a_2.fq.gz"
    rows = (
        f"S1\tMare\t{reads}/run 1/a_1.fq.gz\t{ok}\n"
        f"S2\tMare\t{reads}/gone_1.fq.gz\t{ok}\n"
        f"S3\tMare\trelative/x.fq.gz\t{ok}\n"
        f"S4\tMare\t{reads}/gone_1.fq.gz\t{ok}\n"
    )
    (tmp_path / "bad.tsv").write_text(HEADER + rows)
    result = run(tmp_path, cwd=tmp_path.parent)
    assert result.returncode == 1
    assert "bad.tsv - PROBLEMI: 2 file su 4 non trovati sul server" in result.stdout
    assert f"E17 MANCA  {reads}/gone_1.fq.gz  (colonna File_forward, righe 3, 5)" in result.stdout
    assert "PERCORSO NON ASSOLUTO  relative/x.fq.gz  (colonna File_forward, righe 4)" in (
        result.stdout
    )
    assert "Tabelle da controllare: bad.tsv" in result.stdout


def test_windows_line_endings_bom_and_single_end(reads: Path, tmp_path: Path) -> None:
    content = (
        "﻿Sample\tCategory\tFile\r\n"
        f"S1\tMare\t{reads}/run 1/a_1.fq.gz\r\n\r\n"
        f"S2\tMare\t{reads}/run 1/a_2.fq.gz\r\n"
    )
    (tmp_path / "single.TSV").write_bytes(content.encode("utf-8"))
    result = run(cwd=tmp_path)
    assert result.returncode == 0
    assert "single.TSV - OK: tutti i file (2)" in result.stdout


def test_table_without_file_columns(tmp_path: Path) -> None:
    (tmp_path / "x.tsv").write_text("Sample\tCategory\nS1\tMare\n")
    result = run(cwd=tmp_path)
    assert result.returncode == 1
    assert "non trovo le colonne File_forward / File_reverse / File" in result.stdout


def test_no_tsv_found(tmp_path: Path) -> None:
    result = run(cwd=tmp_path)
    assert result.returncode == 2
    assert "Nessun file .tsv trovato" in result.stderr
