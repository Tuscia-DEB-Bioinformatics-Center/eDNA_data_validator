"""Report aggregation: text and JSON-ready views of a validation result."""

from __future__ import annotations

import json

from .models import Issue, Result, SheetResult
from .schema import CODE_TITLES

_SEVERITY_LABELS = (("error", "ERRORI"), ("warning", "WARNING"), ("info", "INFORMAZIONI"))


def format_rows(rows: list[int]) -> str:
    """Compress row numbers into ranges.

    Args:
        rows: Excel row numbers.

    Returns:
        A string such as ``"2-5, 8, 10-11"``; empty if there are no rows.
    """
    ordered = sorted(set(rows))
    parts: list[str] = []
    start = previous = None
    for number in ordered:
        if previous is not None and number == previous + 1:
            previous = number
            continue
        if start is not None:
            parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    if start is not None:
        parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(parts)


def sheet_outcome(sheet: SheetResult) -> str:
    """Return a short Italian description of what happened to a sheet."""
    if sheet.status == "skipped":
        return "ignorata"
    if sheet.status == "empty":
        return "vuota, saltata"
    if sheet.count("error"):
        return "TSV non generato: correggere gli errori"
    if sheet.count("warning"):
        return "TSV generato: verificare i warning"
    return "TSV generato"


def _issue_to_dict(issue: Issue) -> dict[str, object]:
    return {
        "code": issue.code,
        "title": CODE_TITLES.get(issue.code, ""),
        "severity": issue.severity,
        "sheet": issue.sheet,
        "rows": issue.rows,
        "rows_text": format_rows(issue.rows),
        "column": issue.column,
        "value": issue.value,
        "message": issue.message,
    }


def result_to_dict(result: Result) -> dict[str, object]:
    """Convert a result to plain dictionaries and lists.

    Args:
        result: Validation result.

    Returns:
        A JSON-serialisable dictionary with file issues, sheets, counts and TSV text.
    """
    return {
        "filename": result.filename,
        "has_errors": result.has_errors,
        "file_issues": [_issue_to_dict(issue) for issue in result.file_issues],
        "sheets": [
            {
                "sheet": sheet.sheet,
                "status": sheet.status,
                "pipeline": sheet.pipeline,
                "n_samples": sheet.n_samples,
                "errors": sheet.count("error"),
                "warnings": sheet.count("warning"),
                "outcome": sheet_outcome(sheet),
                "issues": [_issue_to_dict(issue) for issue in sheet.issues],
                "tsv": sheet.tsv,
                "tsv_name": sheet.tsv_name,
            }
            for sheet in result.sheets
        ],
    }


def render_json(result: Result) -> str:
    """Render the result as an indented JSON document.

    Args:
        result: Validation result.

    Returns:
        The JSON text.
    """
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)


def _issue_line(issue: Issue) -> str:
    where = []
    if issue.rows:
        label = "riga" if len(issue.rows) == 1 else "righe"
        where.append(f"{label} {format_rows(issue.rows)}")
    if issue.column:
        where.append(f"colonna {issue.column}")
    prefix = f"[{'; '.join(where)}] " if where else ""
    return f"      - {prefix}{issue.message}"


def render_text(result: Result) -> str:
    """Render the report as plain text, grouped by sheet, severity and code.

    Args:
        result: Validation result.

    Returns:
        The Italian text of the report, ending with a newline.
    """
    lines = [f"Report di validazione eDNA — file: {result.filename}", ""]
    for issue in result.file_issues:
        lines.append(f"{issue.code} — {CODE_TITLES.get(issue.code, '')}: {issue.message}")
    if result.file_issues:
        lines.append("")

    if result.sheets:
        lines.append("RIEPILOGO")
        for sheet in result.sheets:
            if sheet.status == "validated":
                detail = (
                    f"pipeline {sheet.pipeline}, {sheet.n_samples} campioni, "
                    f"{sheet.count('error')} errori, {sheet.count('warning')} warning — "
                )
            else:
                detail = ""
            lines.append(f"  Scheda '{sheet.sheet}': {detail}{sheet_outcome(sheet)}")
        lines.append("")

    for sheet in result.sheets:
        lines.append(f"SCHEDA '{sheet.sheet}'")
        for severity, label in _SEVERITY_LABELS:
            issues = [issue for issue in sheet.issues if issue.severity == severity]
            if not issues:
                continue
            lines.append(f"  {label} ({len(issues)})")
            codes = list(dict.fromkeys(issue.code for issue in issues))
            for code in codes:
                group = [issue for issue in issues if issue.code == code]
                lines.append(f"    {code} — {CODE_TITLES.get(code, '')} ({len(group)})")
                lines.extend(_issue_line(issue) for issue in group)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
