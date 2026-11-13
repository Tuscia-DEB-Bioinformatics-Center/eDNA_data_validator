"""End-to-end tests on the real valid file: report, TSV bytes, CLI and zip."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from conftest import DATA_FILE
from edna_validator.__main__ import main
from edna_validator.core import inspect_json, validate_file, validate_json
from edna_validator.report import format_rows, render_text
from edna_validator.writer import build_zip

PREFIX = "/archive/eDNA_project/raw_data/YYYY_MM_DD/SampleName/RUN_0001/EUKA_1/EUKA_1_"
EXPECTED_HEAD = (
    "Sample\tCategory\tFile_forward\tFile_reverse\tForward\tReverse\n"
    f"Civ_B_2_2\tMare\t{PREFIX}1.fq.gz\t{PREFIX}2.fq.gz\t"
    "NNNcgctcttaTTTGTCTGSTTAATTSCG\tNNNagttagcaCACAGACCTGTTATTGC\n"
    f"Gig_2_2\tMare\t{PREFIX}1.fq.gz\t{PREFIX}2.fq.gz\t"
    "NNNNagacgaacTTTGTCTGSTTAATTSCG\tNNNagttagcaCACAGACCTGTTATTGC\n"
    f"Sab_A_1_2\tLaghi costieri\t{PREFIX}1.fq.gz\t{PREFIX}2.fq.gz\t"
    "NNtgcaagagTTTGTCTGSTTAATTSCG\tNNNagttagcaCACAGACCTGTTATTGC\n"
).encode()


def test_valid_file_report(valid_bytes: bytes) -> None:
    result = validate_file(valid_bytes, "EUKA_lug25.tsv", "eDNA")
    assert not result.has_errors
    sheet = result.sheets[0]
    assert sheet.sheet == "EUKA_lug25"
    assert sheet.n_samples == 72

    warnings = [issue for issue in sheet.issues if issue.severity == "warning"]
    assert [(w.code, w.rows) for w in warnings] == [("W03", [26, 31])]
    assert "'Elba b 1.2'" in warnings[0].message and "'Elba B 1.2'" in warnings[0].message

    summary = next(issue for issue in sheet.issues if issue.code == "I01")
    assert summary.value == "Mare: 66; Laghi costieri: 6"

    normalized = [issue for issue in sheet.issues if issue.code == "I03"]
    assert len(normalized) == 72
    assert normalized[0].message == "'Civ B 2.2' → 'Civ_B_2_2'"


def test_valid_file_tsv_bytes(valid_bytes: bytes) -> None:
    sheet = validate_file(valid_bytes, "EUKA_lug25.tsv", "eDNA").sheets[0]
    output = sheet.tsv.encode("utf-8")
    assert sheet.tsv_name == "EUKA_lug25.tsv"
    assert output.startswith(EXPECTED_HEAD)
    assert not output.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in output
    assert output.count(b"\n") == 73 and output.endswith(b"\n")


def test_auto_detection_matches_explicit_choice(valid_bytes: bytes) -> None:
    sheet = validate_file(valid_bytes, "EUKA_lug25.tsv", "auto").sheets[0]
    assert sheet.pipeline == "eDNA"


def test_text_report_is_grouped(valid_bytes: bytes) -> None:
    text = render_text(validate_file(valid_bytes, "EUKA_lug25.tsv", "eDNA"))
    assert "pipeline eDNA, 72 campioni, 0 errori, 1 warning" in text
    assert "W03 — Campioni che differiscono solo per maiuscole/minuscole (1)" in text
    assert "I03 — Nomi dei campioni normalizzati (72)" in text


def test_format_rows() -> None:
    assert format_rows([5, 2, 3, 4, 8, 10, 11]) == "2-5, 8, 10-11"
    assert format_rows([]) == ""


def test_json_api(valid_bytes: bytes) -> None:
    inspected = json.loads(inspect_json(valid_bytes, "EUKA_lug25.tsv"))
    assert inspected["sheets"][0]["suggested"] == "eDNA"
    assert inspected["sheets"][0]["n_rows"] == 72
    assert "error" in json.loads(inspect_json(b"x", "t.csv"))

    payload = json.loads(validate_json(valid_bytes, "EUKA_lug25.tsv", '{"EUKA_lug25": "eDNA"}'))
    assert payload["has_errors"] is False
    assert payload["sheets"][0]["warnings"] == 1
    assert payload["report_text"].startswith("Report di validazione")


def test_cli_writes_report_and_tsv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(DATA_FILE), "--pipeline", "eDNA", "--out", str(tmp_path)])
    assert code == 0
    assert "W03" in capsys.readouterr().out
    assert (tmp_path / "EUKA_lug25.tsv").read_bytes().startswith(EXPECTED_HEAD)
    assert (tmp_path / "EUKA_lug25_report.txt").read_text(encoding="utf-8").startswith("Report")


def test_cli_exit_code_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "rotta.tsv"
    broken.write_text("Sample\tCategory\tFile\nA\tMare\trelativo.fq.gz\n", encoding="utf-8")
    code = main([str(broken), "--pipeline", "auto", "--json", "--out", str(tmp_path / "out")])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["sheets"][0]["pipeline"] == "eDNA_single_short"
    assert [i["code"] for i in payload["sheets"][0]["issues"] if i["severity"] == "error"] == [
        "E05"
    ]
    assert not (tmp_path / "out" / "rotta.tsv").exists()


def test_zip(valid_bytes: bytes) -> None:
    sheet = validate_file(valid_bytes, "EUKA_lug25.tsv", "eDNA").sheets[0]
    archive = zipfile.ZipFile(io.BytesIO(build_zip({sheet.tsv_name: sheet.tsv})))
    assert archive.namelist() == ["EUKA_lug25.tsv"]
    assert archive.read("EUKA_lug25.tsv") == sheet.tsv.encode("utf-8")
