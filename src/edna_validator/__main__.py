"""Command line interface: ``python -m edna_validator <file> --pipeline ... [--out DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import validate_file
from .report import render_json, render_text
from .schema import AUTO, PIPELINES, SKIP
from .server_check import SERVER_COMMAND
from .server_check import run as run_server_check


def _parse_sheet_options(options: list[str], parser: argparse.ArgumentParser) -> dict[str, str]:
    """Turn ``NAME=PIPELINE`` options into a mapping."""
    mapping: dict[str, str] = {}
    for option in options:
        name, separator, pipeline = option.rpartition("=")
        if not separator or not name:
            parser.error(f"--sheet richiede il formato NOME=PIPELINE (ricevuto: {option})")
        mapping[name] = pipeline
    return mapping


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    ``controllo-server`` runs the cross-check of the FASTQ paths against the server; any other
    arguments run the validator.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 1 if the validation found errors, 0 otherwise.
    """
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == SERVER_COMMAND:
        return run_server_check(argv[1:])

    choices = [*PIPELINES, AUTO]
    parser = argparse.ArgumentParser(
        prog="python -m edna_validator",
        description="Valida una tabella di campioni eDNA (.xlsx o .tsv) e genera i TSV puliti.",
    )
    parser.add_argument("file", type=Path, help="tabella da validare (.xlsx o .tsv)")
    parser.add_argument(
        "--pipeline",
        required=True,
        choices=choices,
        help="pipeline per tutte le schede; 'auto' la deduce dalle colonne",
    )
    parser.add_argument(
        "--sheet",
        action="append",
        default=[],
        metavar="NOME=PIPELINE",
        help=f"pipeline per una singola scheda (ripetibile); '{SKIP}' per ignorarla",
    )
    parser.add_argument("--out", type=Path, help="cartella in cui scrivere TSV e report")
    parser.add_argument("--json", action="store_true", help="report in formato JSON")
    args = parser.parse_args(argv)

    try:
        data = args.file.read_bytes()
    except OSError as exc:
        parser.error(f"impossibile leggere {args.file}: {exc}")

    try:
        result = validate_file(
            data, args.file.name, args.pipeline, _parse_sheet_options(args.sheet, parser)
        )
    except ValueError as exc:
        parser.error(str(exc))

    report = render_json(result) if args.json else render_text(result)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(report if report.endswith("\n") else report + "\n")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        extension = "json" if args.json else "txt"
        report_path = args.out / f"{args.file.stem}_report.{extension}"
        report_path.write_text(report, encoding="utf-8", newline="\n")
        for sheet in result.sheets:
            if sheet.tsv is not None and sheet.tsv_name:
                (args.out / sheet.tsv_name).write_text(sheet.tsv, encoding="utf-8", newline="\n")

    return 1 if result.has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
