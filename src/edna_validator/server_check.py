"""Cross-check of the FASTQ paths in validated TSV files against the server.

The validator itself never reads the server. This check runs only from the command line
(``python -m edna_validator controllo-server ...``) on a computer that can see the reads
folder, for example through a mapped network drive over the VPN.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from .models import Issue
from .readers import ReadError, read_tsv
from .report import format_rows
from .schema import CODE_TITLES, PIPELINES, detect_pipeline

SERVER_COMMAND = "controllo-server"
REPORT_NAME = "controllo_server_report.txt"


def expand_targets(targets: list[str]) -> list[Path]:
    """Turn the command line arguments into the list of TSV files to check.

    Args:
        targets: File paths, folder paths (all ``.tsv`` files inside) or patterns with ``*``.

    Returns:
        The files to check, in the order given.

    Raises:
        ValueError: If a target does not exist or contains no TSV file.
    """
    files: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            found = sorted(
                item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".tsv"
            )
        elif any(char in target for char in "*?["):
            found = sorted(
                Path(match) for match in glob.glob(target) if Path(match).suffix.lower() == ".tsv"
            )
        elif path.is_file():
            found = [path]
        else:
            raise ValueError(f"file o cartella non trovati: {target}")
        if not found:
            raise ValueError(f"nessun file .tsv trovato in: {target}")
        files.extend(found)
    return files


def server_to_local(server_path: str, radice: Path, prefisso: str) -> Path | None:
    """Map a path written in the table to the matching path on the local computer.

    Args:
        server_path: Absolute path of the FASTQ as written in the table.
        radice: Local folder that corresponds to the reads root on the server.
        prefisso: Part of the server path to replace with ``radice``; empty to keep the whole path.

    Returns:
        The local path, or None if ``server_path`` does not start with ``prefisso``.
    """
    relative = server_path
    if prefisso:
        prefix = prefisso.rstrip("/")
        if server_path != prefix and not server_path.startswith(prefix + "/"):
            return None
        relative = server_path[len(prefix) :]
    parts = [part for part in relative.split("/") if part]
    return radice.joinpath(*parts)


def check_tsv(data: bytes, filename: str, radice: Path, prefisso: str) -> tuple[list[Issue], int]:
    """Check that every FASTQ path of one TSV exists under the local reads root.

    Args:
        data: Raw content of the TSV file.
        filename: File name, used to name the dataset.
        radice: Local folder that corresponds to the reads root on the server.
        prefisso: Server path prefix to replace with ``radice``; empty for none.

    Returns:
        A tuple ``(issues, checked)``: the E18/E19 issues and the number of distinct paths checked.

    Raises:
        ReadError: If the TSV cannot be read.
    """
    dataset = read_tsv(data, Path(filename).stem)
    columns = [*dataset.columns, *dataset.duplicate_columns]
    pipeline = PIPELINES[detect_pipeline(columns)[0]]

    issues: list[Issue] = []
    checked = 0
    for column in pipeline.file_columns:
        if column not in dataset.columns:
            continue
        rows_by_path: dict[str, list[int]] = {}
        for row in dataset.rows:
            value = row.values[column]
            if value:
                rows_by_path.setdefault(value, []).append(row.number)
        checked += len(rows_by_path)
        for value, rows in rows_by_path.items():
            local = server_to_local(value, radice, prefisso)
            if local is None:
                issues.append(
                    Issue.create(
                        "E19",
                        dataset.name,
                        f"Il percorso '{value}' non inizia con '{prefisso}': non si può cercare "
                        "sotto la radice indicata. Controlla il percorso nella tabella oppure "
                        "l'opzione --prefisso.",
                        rows,
                        column,
                        value,
                    )
                )
            elif not local.is_file():
                issues.append(
                    Issue.create(
                        "E18",
                        dataset.name,
                        f"Il file '{value}' non esiste sul server: nella cartella controllata "
                        f"('{local}') non c'è. Verifica che il percorso sia quello reale, che il "
                        "file non sia stato spostato o rinominato e che la VPN sia attiva.",
                        rows,
                        column,
                        value,
                    )
                )
    return issues, checked


def render_server_report(filename: str, issues: list[Issue], checked: int) -> str:
    """Render the outcome of the server check for one TSV file as plain text.

    Args:
        filename: TSV file name.
        issues: E18/E19 issues found in the file.
        checked: Number of distinct paths checked.

    Returns:
        The Italian text of the report, ending with a newline.
    """
    lines = [f"Controllo sul server — file: {filename}", f"Percorsi controllati: {checked}", ""]
    for issue in sorted(issues, key=lambda item: (item.code, min(item.rows or [0]))):
        lines.append(
            f"{issue.code} — {CODE_TITLES.get(issue.code, '')}: {issue.message} "
            f"Righe: {format_rows(issue.rows)}."
        )
    if issues:
        lines.append("")
        lines.append(
            f"Esito: {len(issues)} {'problema' if len(issues) == 1 else 'problemi'} sul server. "
            "Il TSV non va usato finché i file "
            "mancanti non sono sistemati."
        )
    else:
        lines.append("Esito: tutti i file indicati nel TSV sono presenti sul server.")
    return "\n".join(lines) + "\n"


def run(argv: list[str]) -> int:
    """Run the server check from the command line.

    Args:
        argv: Arguments after ``controllo-server``.

    Returns:
        0 if every file was found, 1 if some file is missing or outside the root, 2 if the
        check could not run (unreachable root, unreadable file, bad arguments).
    """
    parser = argparse.ArgumentParser(
        prog=f"python -m edna_validator {SERVER_COMMAND}",
        description="Controlla che i FASTQ indicati nelle tabelle TSV esistano sul server.",
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="file .tsv, cartella che contiene i TSV, oppure modello con jolly (es. out\\*.tsv)",
    )
    parser.add_argument(
        "--radice",
        required=True,
        type=Path,
        help="cartella del proprio computer che corrisponde alla radice dei reads sul server",
    )
    parser.add_argument(
        "--prefisso",
        default="",
        help="inizio dei percorsi della tabella da sostituire con --radice (es. "
        "/archive/progetto/reads); se omesso, il percorso intero viene cercato sotto --radice",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=f"cartella in cui salvare {REPORT_NAME} (default: cartella del primo file)",
    )
    args = parser.parse_args(argv)

    if not args.radice.is_dir():
        print(
            f"La cartella {args.radice} non è raggiungibile. Controlla che l'unità di rete sia "
            "collegata e che la VPN sia attiva.",
            file=sys.stderr,
        )
        return 2
    try:
        files = expand_targets(args.targets)
    except ValueError as exc:
        parser.error(str(exc))

    reports: list[str] = []
    failed_files = 0
    for file in files:
        try:
            data = file.read_bytes()
        except OSError as exc:
            print(f"Impossibile leggere {file}: {exc}", file=sys.stderr)
            return 2
        try:
            issues, checked = check_tsv(data, file.name, args.radice, args.prefisso)
        except ReadError as exc:
            print(f"{file.name}: {exc}", file=sys.stderr)
            failed_files += 1
            continue
        if issues:
            failed_files += 1
        reports.append(render_server_report(file.name, issues, checked))

    files_word = "file controllato" if len(files) == 1 else "file controllati"
    summary = f"Totale: {len(files)} {files_word}, {failed_files} con problemi."
    report = ("\n" + "=" * 60 + "\n").join(reports) + "\n" + summary + "\n"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(report)

    out_dir = args.out or files[0].parent
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / REPORT_NAME).write_text(report, encoding="utf-8", newline="\n")

    return 1 if failed_files else 0
