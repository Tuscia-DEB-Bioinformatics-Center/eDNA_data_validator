"""Validation rules: one check = one function, listed in ``RULES``.

Each rule receives the cleaned dataset and the pipeline and returns a list of issues.
Rules skip empty cells and missing columns on their own, so a missing column (E01) or
an empty cell (E02) never produces cascading errors.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterator
from itertools import combinations

from .cleaning import normalize_sample
from .models import Dataset, Issue
from .schema import (
    ADAPTER_ALPHABET,
    CATEGORY,
    CATEGORY_SIMILARITY_THRESHOLD,
    DEFAULT_CATEGORY,
    FILE_FORWARD,
    FILE_REVERSE,
    LAYOUT_BREAKING_CHARS,
    OTHER_COMPRESSION_EXTENSIONS,
    PATH_ALLOWED_CHARS,
    SAMPLE,
    UNCOMPRESSED_EXTENSIONS,
    VALID_EXTENSIONS,
    Pipeline,
    similar_name,
)

Rule = Callable[[Dataset, Pipeline], list[Issue]]


def _cells(ds: Dataset, columns: tuple[str, ...]) -> Iterator[tuple[int, str, str]]:
    """Yield ``(row, column, value)`` for the non-empty cells of the present columns."""
    for column in columns:
        if column not in ds.columns:
            continue
        for row in ds.rows:
            value = row.values[column]
            if value:
                yield row.number, column, value


def _grouped(
    ds: Dataset, columns: tuple[str, ...], predicate: Callable[[str], bool]
) -> dict[tuple[str, str], list[int]]:
    """Group the rows of the cells matching ``predicate`` by ``(column, value)``."""
    groups: dict[tuple[str, str], list[int]] = {}
    for number, column, value in _cells(ds, columns):
        if predicate(value):
            groups.setdefault((column, value), []).append(number)
    return groups


def _describe_char(char: str) -> str:
    """Return a readable description of a character, with code point when needed."""
    if char.isascii() and char.isprintable():
        return f"'{char}'"
    if char.isprintable():
        return f"'{char}' (U+{ord(char):04X})"
    return f"carattere invisibile U+{ord(char):04X}"


def _bad_chars(value: str, is_bad: Callable[[str], bool]) -> str:
    """List the offending characters of a value with their 1-based positions."""
    found = [
        f"{_describe_char(char)} in posizione {position}"
        for position, char in enumerate(value, start=1)
        if is_bad(char)
    ]
    return ", ".join(found)


def _samples(ds: Dataset) -> Iterator[tuple[int, str, str]]:
    """Yield ``(row, original, normalized)`` for the non-empty Sample cells."""
    for number, _, value in _cells(ds, (SAMPLE,)):
        yield number, value, normalize_sample(value)


def _similar_column(missing: str, ds: Dataset, pipeline: Pipeline) -> str | None:
    """Find a header that looks like the missing column (case, spaces, typos)."""
    return similar_name(missing, [c for c in ds.columns if c not in pipeline.columns])


def missing_columns(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E01: required column missing or present more than once."""
    issues = []
    for column in pipeline.columns:
        if column in ds.duplicate_columns:
            issues.append(
                Issue.create(
                    "E01",
                    ds.name,
                    f"La colonna '{column}' compare più volte nell'intestazione: lasciane "
                    "una sola. Finché è ripetuta, i controlli su questa colonna non vengono "
                    "eseguiti.",
                    [1],
                    column,
                )
            )
            continue
        if column in ds.columns:
            continue
        similar = _similar_column(column, ds, pipeline)
        hint = (
            f" È presente una colonna simile, '{similar}': rinominala esattamente '{column}' "
            "(maiuscole e trattini bassi inclusi)."
            if similar
            else f" Aggiungi la colonna con il nome esatto '{column}' nella riga 1."
        )
        issues.append(
            Issue.create(
                "E01",
                ds.name,
                f"Manca la colonna obbligatoria '{column}' per la pipeline {pipeline.name}.{hint}",
                [1],
                column,
                similar,
            )
        )
    return issues


def empty_required_cells(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E02: empty cell in a required column other than Category."""
    issues = []
    for column in pipeline.columns:
        if column == CATEGORY or column not in ds.columns:
            continue
        rows = [
            row.number
            for row in ds.rows
            if not row.values[column] and (row.number, column) not in ds.formula_cells
        ]
        if rows:
            issues.append(
                Issue.create(
                    "E02",
                    ds.name,
                    f"Celle vuote nella colonna obbligatoria '{column}': compila il valore "
                    "oppure elimina le righe che non sono campioni.",
                    rows,
                    column,
                )
            )
    return issues


def empty_normalized_samples(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E03: Sample that becomes empty after normalisation."""
    groups: dict[str, list[int]] = {}
    for number, original, normalized in _samples(ds):
        if not normalized:
            groups.setdefault(original, []).append(number)
    return [
        Issue.create(
            "E03",
            ds.name,
            f"Il nome del campione '{original}' non contiene lettere o cifre e resta vuoto "
            "dopo la normalizzazione: usa un nome con lettere (non accentate) o cifre.",
            rows,
            SAMPLE,
            original,
        )
        for original, rows in groups.items()
    ]


def duplicate_samples(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E04: duplicated Sample, compared on the normalised names."""
    groups: dict[str, list[tuple[int, str]]] = {}
    for number, original, normalized in _samples(ds):
        if normalized:
            groups.setdefault(normalized, []).append((number, original))
    issues = []
    for normalized, members in groups.items():
        if len(members) < 2:
            continue
        listing = ", ".join(f"'{original}' (riga {number})" for number, original in members)
        issues.append(
            Issue.create(
                "E04",
                ds.name,
                f"Più campioni diventano '{normalized}' dopo la normalizzazione: {listing}. "
                "Ogni campione deve avere un nome unico: rinomina o elimina i duplicati.",
                [number for number, _ in members],
                SAMPLE,
                normalized,
            )
        )
    return issues


def relative_paths(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E05: path that does not start with ``/``."""
    groups = _grouped(ds, pipeline.file_columns, lambda value: not value.startswith("/"))
    return [
        Issue.create(
            "E05",
            ds.name,
            f"Il percorso '{value}' non è assoluto: deve iniziare con '/' e indicare la "
            "posizione completa del file sul server.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def _is_plain_space(char: str) -> bool:
    return char.isspace() and char not in LAYOUT_BREAKING_CHARS


def spaces_in_paths(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E06: space (of any kind) inside a path."""
    groups = _grouped(
        ds, pipeline.file_columns, lambda value: any(_is_plain_space(c) for c in value)
    )
    return [
        Issue.create(
            "E06",
            ds.name,
            f"Il percorso '{value}' contiene spazi ({_bad_chars(value, _is_plain_space)}): "
            "rinomina file/cartelle sul server senza spazi e aggiorna la tabella.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def uncompressed_fastq(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E07: FASTQ that is not compressed (``.fq`` / ``.fastq``, case-insensitive)."""
    groups = _grouped(
        ds, pipeline.file_columns, lambda value: value.lower().endswith(UNCOMPRESSED_EXTENSIONS)
    )
    return [
        Issue.create(
            "E07",
            ds.name,
            f"Il file '{value}' è un FASTQ non compresso: comprimilo con gzip sul server "
            "(estensione .fq.gz o .fastq.gz) e aggiorna il percorso nella tabella.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def identical_forward_reverse(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E08: File_forward identical to File_reverse on the same row (paired-end)."""
    if not pipeline.paired or not {FILE_FORWARD, FILE_REVERSE} <= set(ds.columns):
        return []
    groups: dict[str, list[int]] = {}
    for row in ds.rows:
        forward = row.values[FILE_FORWARD]
        if forward and forward == row.values[FILE_REVERSE]:
            groups.setdefault(forward, []).append(row.number)
    return [
        Issue.create(
            "E08",
            ds.name,
            f"'{FILE_FORWARD}' e '{FILE_REVERSE}' indicano lo stesso file '{value}': "
            "indica il file delle letture forward e quello delle letture reverse.",
            rows,
            FILE_REVERSE,
            value,
        )
        for value, rows in groups.items()
    ]


def _is_bad_adapter_char(char: str) -> bool:
    return char.upper() not in ADAPTER_ALPHABET and char not in LAYOUT_BREAKING_CHARS


def invalid_adapters(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E09: adapter with characters outside the IUPAC nucleotide alphabet."""
    groups = _grouped(
        ds, pipeline.adapter_columns, lambda value: any(_is_bad_adapter_char(c) for c in value)
    )
    return [
        Issue.create(
            "E09",
            ds.name,
            f"L'adattatore '{value}' contiene caratteri non validi: "
            f"{_bad_chars(value, _is_bad_adapter_char)}. Sono ammesse solo le lettere "
            f"{ADAPTER_ALPHABET} (maiuscole o minuscole).",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def duplicate_combinations(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E10: same combination of files and adapters on several rows (demultiplexing)."""
    key_columns = pipeline.file_columns + pipeline.adapter_columns
    if not pipeline.demultiplex or not set(key_columns) <= set(ds.columns):
        return []
    groups: dict[tuple[str, ...], list[int]] = {}
    for row in ds.rows:
        files = [row.values[column] for column in pipeline.file_columns]
        adapters = [row.values[column].upper() for column in pipeline.adapter_columns]
        if all(files) and all(adapters):
            groups.setdefault((*files, *adapters), []).append(row.number)
    issues = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        adapters = " / ".join(key[len(pipeline.file_columns) :])
        issues.append(
            Issue.create(
                "E10",
                ds.name,
                f"{len(rows)} campioni hanno gli stessi file e la stessa coppia di adattatori "
                f"({adapters}): non si possono distinguere nel demultiplexing. Correggi gli "
                "adattatori o i file di una delle righe.",
                rows,
                None,
                adapters,
            )
        )
    return issues


def repeated_files(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E11: same file on more than one row, also across columns (no demultiplexing)."""
    if pipeline.demultiplex:
        return []
    usage: dict[str, list[tuple[int, str]]] = {}
    for number, column, value in _cells(ds, pipeline.file_columns):
        usage.setdefault(value, []).append((number, column))
    issues = []
    for value, places in usage.items():
        rows = sorted({number for number, _ in places})
        if len(rows) < 2:
            continue
        columns = sorted({column for _, column in places})
        issues.append(
            Issue.create(
                "E11",
                ds.name,
                f"Il file '{value}' compare in {len(rows)} righe: nelle pipeline senza "
                "demultiplexing ogni file appartiene a un solo campione. Correggi i percorsi.",
                rows,
                ", ".join(columns),
                value,
            )
        )
    return issues


def layout_breaking_cells(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E12: tab or line break inside a cell written to the TSV."""
    issues = []
    for column in pipeline.columns:
        rows = [
            number
            for number, _, value in _cells(ds, (column,))
            if any(char in LAYOUT_BREAKING_CHARS for char in value)
        ]
        if rows:
            issues.append(
                Issue.create(
                    "E12",
                    ds.name,
                    f"Celle della colonna '{column}' con una tabulazione o un a capo interno "
                    "(Alt+Invio in Excel): rimuovili, altrimenti il file TSV risulta spezzato.",
                    rows,
                    column,
                )
            )
    return issues


def converted_samples(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E13: Sample stored by Excel as a number or a date."""
    return [
        Issue.create(
            "E13",
            ds.name,
            f"Excel ha salvato il nome del campione come {cell.kind} ('{cell.text}'): il "
            "testo originale può essere stato alterato (es. 1.10 diventa 1.1). Imposta la "
            "cella come Testo e riscrivi il nome.",
            [cell.row],
            SAMPLE,
            cell.text,
        )
        for cell in ds.converted
        if cell.column == SAMPLE
    ]


def formulas_without_value(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """E14: formula whose result was never saved in the file."""
    groups: dict[str, list[int]] = {}
    for number, column in ds.formula_cells:
        if column in pipeline.columns:
            groups.setdefault(column, []).append(number)
    return [
        Issue.create(
            "E14",
            ds.name,
            f"Celle della colonna '{column}' con una formula di cui il file non contiene il "
            "risultato: apri il file in Excel e salvalo di nuovo, oppure sostituisci le "
            "formule con i valori (Copia, Incolla speciale, Valori).",
            rows,
            column,
        )
        for column, rows in sorted(groups.items())
    ]


def empty_categories(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W01: empty Category, replaced by the default category."""
    if CATEGORY not in ds.columns:
        return []
    rows = [
        row.number
        for row in ds.rows
        if not row.values[CATEGORY] and (row.number, CATEGORY) not in ds.formula_cells
    ]
    if not rows:
        return []
    return [
        Issue.create(
            "W01",
            ds.name,
            f"Categoria vuota: è stata assegnata '{DEFAULT_CATEGORY}'. Aggiungi la categoria "
            "corretta, perché la pipeline analizza ogni categoria separatamente.",
            rows,
            CATEGORY,
        )
    ]


def similar_categories(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W02: categories that look like variants of the same name."""
    rows_by_category: dict[str, list[int]] = {}
    for number, _, value in _cells(ds, (CATEGORY,)):
        rows_by_category.setdefault(value, []).append(number)

    def key(name: str) -> str:
        return "".join(name.lower().split())

    groups: dict[str, list[str]] = {}
    for name in rows_by_category:
        groups.setdefault(key(name), []).append(name)

    def issue(names: list[str] | tuple[str, ...], detail: str) -> Issue:
        listing = ", ".join(f"'{n}' ({len(rows_by_category[n])} campioni)" for n in names)
        return Issue.create(
            "W02",
            ds.name,
            f"Categorie simili: {listing}. {detail} Se è la stessa categoria, scrivila in un "
            "solo modo; il validatore non la corregge in automatico.",
            [number for name in names for number in rows_by_category[name]],
            CATEGORY,
            " / ".join(names),
        )

    issues = [
        issue(names, "Differiscono solo per maiuscole o spazi.")
        for names in groups.values()
        if len(names) > 1
    ]
    for first, second in combinations(rows_by_category, 2):
        if key(first) == key(second):
            continue
        ratio = difflib.SequenceMatcher(None, first.lower(), second.lower()).ratio()
        if ratio >= CATEGORY_SIMILARITY_THRESHOLD:
            issues.append(issue((first, second), "I nomi sono quasi uguali."))
    return issues


def case_only_samples(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W03: samples whose normalised names differ only by letter case."""
    groups: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for number, original, normalized in _samples(ds):
        if normalized:
            groups.setdefault(normalized.lower(), {}).setdefault(normalized, []).append(
                (number, original)
            )
    issues = []
    for variants in groups.values():
        if len(variants) < 2:
            continue
        members = [member for group in variants.values() for member in group]
        listing = ", ".join(f"'{original}' (riga {number})" for number, original in members)
        issues.append(
            Issue.create(
                "W03",
                ds.name,
                f"Campioni che differiscono solo per maiuscole/minuscole: {listing}. Conferma "
                "se è un refuso oppure se sono davvero campioni distinti.",
                [number for number, _ in members],
                SAMPLE,
                " / ".join(variants),
            )
        )
    return issues


def hyphens_in_paths(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W04: hyphen in a path."""
    groups = _grouped(ds, pipeline.file_columns, lambda value: "-" in value)
    return [
        Issue.create(
            "W04",
            ds.name,
            f"Il percorso '{value}' contiene il trattino '-': sostituiscilo con '_' "
            "rinominando file/cartelle sul server e aggiornando la tabella. Il validatore "
            "non modifica i percorsi.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def _is_disallowed_path_char(char: str) -> bool:
    return char not in PATH_ALLOWED_CHARS and char != "-" and not char.isspace()


def disallowed_path_chars(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W05: character not allowed in a path (hyphen and spaces have their own rules)."""
    groups = _grouped(
        ds, pipeline.file_columns, lambda value: any(_is_disallowed_path_char(c) for c in value)
    )
    return [
        Issue.create(
            "W05",
            ds.name,
            f"Il percorso '{value}' contiene caratteri non ammessi: "
            f"{_bad_chars(value, _is_disallowed_path_char)}. Sono ammessi solo lettere non "
            "accentate, cifre e i simboli _ / + . Verifica il percorso o rinomina sul server.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def _extension_problem(path: str) -> str | None:
    """Describe what is wrong with the extension of a path, None if nothing (or E07)."""
    if path.endswith(VALID_EXTENSIONS):
        return None
    lowered = path.lower()
    if lowered.endswith(UNCOMPRESSED_EXTENSIONS):
        return None
    if lowered.endswith(VALID_EXTENSIONS):
        return "l'estensione è scritta in maiuscolo: rinomina il file con estensione minuscola"
    for extension in OTHER_COMPRESSION_EXTENSIONS:
        if lowered.endswith(extension):
            return f"la compressione {extension} non è quella attesa: ricomprimi il file con gzip"
    if re.search(r"\.(fq|fastq)\.[^./]+$", lowered) or lowered.endswith((".gz", ".gzip")):
        return "il file sembra un FASTQ compresso ma con un nome non standard: rinominalo"
    return "l'estensione non è riconosciuta: verifica che sia un FASTQ compresso con gzip"


def nonstandard_extensions(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W06: extension other than ``.fq.gz`` / ``.fastq.gz``."""
    groups = _grouped(
        ds, pipeline.file_columns, lambda value: _extension_problem(value) is not None
    )
    return [
        Issue.create(
            "W06",
            ds.name,
            f"Il file '{value}' non termina con .fq.gz o .fastq.gz: "
            f"{_extension_problem(value)} e aggiorna la tabella.",
            rows,
            column,
            value,
        )
        for (column, value), rows in groups.items()
    ]


def converted_cells(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """W07: cell of a text column stored by Excel as a number or a date."""
    return [
        Issue.create(
            "W07",
            ds.name,
            f"Excel ha salvato la cella della colonna '{cell.column}' come {cell.kind}: è "
            f"stata letta come '{cell.text}'. Verifica che sia il valore voluto; per evitarlo "
            "imposta la cella come Testo.",
            [cell.row],
            cell.column,
            cell.text,
        )
        for cell in ds.converted
        if cell.column in pipeline.columns and cell.column != SAMPLE
    ]


def category_summary(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """I01: categories with their number of samples."""
    if CATEGORY not in ds.columns:
        return []
    counts: dict[str, int] = {}
    for row in ds.rows:
        category = row.values[CATEGORY] or DEFAULT_CATEGORY
        counts[category] = counts.get(category, 0) + 1
    listing = "; ".join(f"{name}: {count}" for name, count in counts.items())
    return [
        Issue.create(
            "I01",
            ds.name,
            f"Categorie trovate ({len(counts)}) e numero di campioni — {listing}.",
            None,
            CATEGORY,
            listing,
        )
    ]


def extra_columns(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """I02: columns that are not used by the pipeline."""
    extras = [
        column for column in (*ds.columns, *ds.duplicate_columns) if column not in pipeline.columns
    ]
    parts = []
    if extras:
        parts.append("Colonne non usate dalla pipeline e ignorate: " + ", ".join(extras) + ".")
    if ds.unnamed_columns:
        parts.append(f"Ignorate anche {ds.unnamed_columns} colonne con dati ma senza intestazione.")
    if not parts:
        return []
    return [Issue.create("I02", ds.name, " ".join(parts), None, None, ", ".join(extras) or None)]


def normalized_samples(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
    """I03: sample names changed by the normalisation."""
    return [
        Issue.create(
            "I03",
            ds.name,
            f"'{original}' → '{normalized}'",
            [number],
            SAMPLE,
            original,
        )
        for number, original, normalized in _samples(ds)
        if normalized and normalized != original
    ]


# Active rules, in report order. To add a rule: write a function and append it here.
RULES: list[Rule] = [
    missing_columns,
    empty_required_cells,
    empty_normalized_samples,
    duplicate_samples,
    relative_paths,
    spaces_in_paths,
    uncompressed_fastq,
    identical_forward_reverse,
    invalid_adapters,
    duplicate_combinations,
    repeated_files,
    layout_breaking_cells,
    converted_samples,
    formulas_without_value,
    empty_categories,
    similar_categories,
    case_only_samples,
    hyphens_in_paths,
    disallowed_path_chars,
    nonstandard_extensions,
    converted_cells,
    category_summary,
    extra_columns,
    normalized_samples,
]
