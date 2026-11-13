"""Entry points of the engine: bytes + file name in, ``Result`` out. No network, no browser."""

from __future__ import annotations

import json

from .cleaning import normalize_sample
from .models import Dataset, Issue, Result, SheetResult
from .readers import ReadError, read_file
from .report import render_text, result_to_dict
from .rules import RULES
from .schema import AUTO, PIPELINES, SKIP, detect_pipeline
from .writer import dataset_to_tsv

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def validate_dataset(
    dataset: Dataset, pipeline_name: str, detection_reason: str | None = None
) -> SheetResult:
    """Run every registered rule on one dataset.

    Args:
        dataset: Cleaned dataset.
        pipeline_name: Name of the pipeline to validate against.
        detection_reason: Explanation of the automatic choice, None if chosen by the user.

    Returns:
        The sheet result, with the clean TSV when there are no errors.

    Raises:
        ValueError: If the pipeline name is unknown.
    """
    if pipeline_name not in PIPELINES:
        raise ValueError(f"Pipeline sconosciuta: {pipeline_name}")
    pipeline = PIPELINES[pipeline_name]
    if detection_reason:
        message = f"Pipeline {pipeline.name}, dedotta dalle colonne: {detection_reason}."
    else:
        message = f"Pipeline {pipeline.name}, scelta dall'utente."
    issues = [Issue.create("I04", dataset.name, message, None, None, pipeline.name)]
    for rule in RULES:
        issues.extend(rule(dataset, pipeline))
    issues.sort(key=lambda issue: _SEVERITY_ORDER[issue.severity])

    result = SheetResult(
        sheet=dataset.name,
        status="validated",
        pipeline=pipeline.name,
        n_samples=len(dataset.rows),
        issues=issues,
    )
    if not result.count("error"):
        result.tsv = dataset_to_tsv(dataset, pipeline)
    return result


def _header(dataset: Dataset) -> list[str]:
    """Return every header name of a dataset, repeated ones included."""
    return [*dataset.columns, *dataset.duplicate_columns]


def _assign_tsv_names(sheets: list[SheetResult]) -> None:
    """Give each validated sheet a unique output file name (I06 when adjusted)."""
    used: set[str] = set()
    for index, sheet in enumerate(sheets, start=1):
        if sheet.status != "validated":
            continue
        natural = normalize_sample(sheet.sheet)
        base = natural or f"scheda_{index}"
        name, suffix = base, 2
        while name.lower() in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name.lower())
        sheet.tsv_name = f"{name}.tsv"
        if name != natural:
            reason = (
                "il nome della scheda non contiene lettere o cifre"
                if not natural
                else "un'altra scheda produce lo stesso nome di file"
            )
            sheet.issues.append(
                Issue.create(
                    "I06",
                    sheet.sheet,
                    f"Il file TSV di questa scheda si chiama '{sheet.tsv_name}' perché {reason}.",
                    None,
                    None,
                    sheet.tsv_name,
                )
            )


def validate_file(
    data: bytes,
    filename: str,
    pipeline: str = AUTO,
    sheet_pipelines: dict[str, str] | None = None,
) -> Result:
    """Validate a whole input file without stopping at the first error.

    Args:
        data: Raw content of the .xlsx or .tsv file.
        filename: Original file name.
        pipeline: Pipeline for every sheet: a pipeline name, ``auto`` or ``skip``.
        sheet_pipelines: Per-sheet overrides, mapping sheet name to the same values.

    Returns:
        The validation result for the file.

    Raises:
        ValueError: If a pipeline name or a sheet name in ``sheet_pipelines`` is unknown.
    """
    overrides = sheet_pipelines or {}
    for choice in (pipeline, *overrides.values()):
        if choice not in PIPELINES and choice not in (AUTO, SKIP):
            raise ValueError(f"Pipeline sconosciuta: {choice}")

    result = Result(filename=filename)
    try:
        datasets = read_file(data, filename)
    except ReadError as exc:
        result.file_issues.append(Issue.create("E00", "", str(exc)))
        return result

    unknown = set(overrides) - {dataset.name for dataset in datasets}
    if unknown:
        raise ValueError(f"Schede non presenti nel file: {', '.join(sorted(unknown))}")

    for dataset in datasets:
        choice = overrides.get(dataset.name, pipeline)
        if choice == SKIP:
            message = "Scheda ignorata su richiesta dell'utente."
            sheet = SheetResult(dataset.name, "skipped")
        elif not dataset.rows:
            detail = "contiene solo l'intestazione" if dataset.columns else "è vuota"
            message = f"La scheda {detail}: è stata saltata."
            sheet = SheetResult(dataset.name, "empty")
        else:
            if choice == AUTO:
                name, reason = detect_pipeline(_header(dataset))
                sheet = validate_dataset(dataset, name, reason)
            else:
                sheet = validate_dataset(dataset, choice)
            result.sheets.append(sheet)
            continue
        sheet.issues.append(Issue.create("I05", dataset.name, message))
        result.sheets.append(sheet)

    _assign_tsv_names(result.sheets)
    return result


def inspect_json(data: bytes, filename: str) -> str:
    """Describe the sheets of a file so that a front-end can ask for the pipelines.

    Args:
        data: Raw content of the file.
        filename: Original file name.

    Returns:
        JSON text: ``{"error": message}`` if the file is unreadable, otherwise
        ``{"sheets": [...]}`` with columns, row count and suggested pipeline per sheet.
    """
    try:
        datasets = read_file(data, filename)
    except ReadError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    sheets = []
    for dataset in datasets:
        suggested, reason = detect_pipeline(_header(dataset))
        sheets.append(
            {
                "sheet": dataset.name,
                "columns": _header(dataset),
                "n_rows": len(dataset.rows),
                "empty": not dataset.rows,
                "suggested": suggested,
                "reason": reason,
            }
        )
    return json.dumps({"sheets": sheets}, ensure_ascii=False)


def validate_json(data: bytes, filename: str, sheet_pipelines_json: str = "{}") -> str:
    """Validate a file and return everything a front-end needs as JSON.

    Args:
        data: Raw content of the file.
        filename: Original file name.
        sheet_pipelines_json: JSON object mapping sheet name to pipeline, ``auto`` or ``skip``.

    Returns:
        JSON text of the result, with the plain-text report under ``report_text``.
    """
    result = validate_file(data, filename, AUTO, json.loads(sheet_pipelines_json))
    payload = result_to_dict(result)
    payload["report_text"] = render_text(result)
    return json.dumps(payload, ensure_ascii=False)
