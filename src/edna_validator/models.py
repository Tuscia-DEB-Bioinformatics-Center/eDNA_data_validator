"""Data models shared by readers, rules, report and writer."""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import SEVERITIES


@dataclass
class Issue:
    """One finding of the validator.

    Attributes:
        code: Rule code (E04, W03, I01...).
        severity: ``error``, ``warning`` or ``info``.
        sheet: Name of the sheet/dataset, empty for file-level issues.
        message: Italian message for the wet lab, including what to fix.
        rows: Excel row numbers involved.
        column: Column involved, if any.
        value: Offending value, if any.
    """

    code: str
    severity: str
    sheet: str
    message: str
    rows: list[int] = field(default_factory=list)
    column: str | None = None
    value: str | None = None

    @classmethod
    def create(
        cls,
        code: str,
        sheet: str,
        message: str,
        rows: list[int] | None = None,
        column: str | None = None,
        value: str | None = None,
    ) -> Issue:
        """Build an issue deriving the severity from the first letter of the code.

        Args:
            code: Rule code.
            sheet: Sheet name.
            message: Italian message.
            rows: Excel rows involved.
            column: Column involved.
            value: Offending value.

        Returns:
            The new issue.
        """
        return cls(code, SEVERITIES[code[0]], sheet, message, sorted(rows or []), column, value)


@dataclass
class Row:
    """One data row: Excel row number and trimmed values by column name."""

    number: int
    values: dict[str, str]


@dataclass
class ConvertedCell:
    """A cell that the spreadsheet stored as a non-text value."""

    row: int
    column: str
    kind: str
    text: str


@dataclass
class Dataset:
    """One table (a sheet of a workbook or a TSV file) after cleaning.

    Attributes:
        name: Sheet name, or file name without extension for TSV input.
        columns: Trimmed, non-empty header names that appear once, in table order.
        rows: Non-empty data rows.
        duplicate_columns: Header names that appear more than once (not in columns).
        unnamed_columns: Number of columns holding data under an empty header.
        converted: Cells stored as number/date/boolean by the spreadsheet.
        formula_cells: ``(row, column)`` of formulas without a cached value.
    """

    name: str
    columns: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    duplicate_columns: list[str] = field(default_factory=list)
    unnamed_columns: int = 0
    converted: list[ConvertedCell] = field(default_factory=list)
    formula_cells: set[tuple[int, str]] = field(default_factory=set)


@dataclass
class SheetResult:
    """Validation outcome of one sheet.

    Attributes:
        sheet: Sheet name.
        status: ``validated``, ``empty`` or ``skipped``.
        pipeline: Pipeline used, None when the sheet was not validated.
        n_samples: Number of data rows.
        issues: All issues of the sheet.
        tsv: Clean TSV content, None when the sheet has errors or was not validated.
        tsv_name: Output file name for the TSV.
    """

    sheet: str
    status: str
    pipeline: str | None = None
    n_samples: int = 0
    issues: list[Issue] = field(default_factory=list)
    tsv: str | None = None
    tsv_name: str | None = None

    def count(self, severity: str) -> int:
        """Return the number of issues with the given severity."""
        return sum(1 for issue in self.issues if issue.severity == severity)


@dataclass
class Result:
    """Validation outcome of a whole input file."""

    filename: str
    sheets: list[SheetResult] = field(default_factory=list)
    file_issues: list[Issue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Return True if the file or any of its sheets has at least one error."""
        issues = list(self.file_issues)
        for sheet in self.sheets:
            issues.extend(sheet.issues)
        return any(issue.severity == "error" for issue in issues)
