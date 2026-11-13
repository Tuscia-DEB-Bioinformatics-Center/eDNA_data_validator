"""Pipeline definitions, column names and tunable constants.

Everything that the bioinformatics group may want to change (thresholds,
allowed character sets, pipeline columns) lives here as plain data.
"""

from __future__ import annotations

import difflib
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass

SAMPLE = "Sample"
CATEGORY = "Category"
FILE = "File"
FILE_FORWARD = "File_forward"
FILE_REVERSE = "File_reverse"
FORWARD = "Forward"
REVERSE = "Reverse"

DEFAULT_CATEGORY = "Uncategorized"

# W02: second-level similarity threshold (difflib ratio on lowercased names).
CATEGORY_SIMILARITY_THRESHOLD = 0.90

# E09: IUPAC nucleotide codes accepted in adapters (case-insensitive).
ADAPTER_ALPHABET = "ACGTRYSWKMBDHVN"

# W05: characters accepted in file paths. Hyphen and whitespace have their own rules.
PATH_ALLOWED_CHARS = frozenset(string.ascii_letters + string.digits + "_/+.")

# E12: whitespace that would break the TSV layout when found inside a cell.
LAYOUT_BREAKING_CHARS = frozenset("\t\n\r\v\f")

VALID_EXTENSIONS = (".fq.gz", ".fastq.gz")
UNCOMPRESSED_EXTENSIONS = (".fq", ".fastq")
OTHER_COMPRESSION_EXTENSIONS = (".bz2", ".xz", ".zst", ".zip")

AUTO = "auto"
SKIP = "skip"


@dataclass(frozen=True)
class Pipeline:
    """Description of one eDNA pipeline input format.

    Attributes:
        name: Pipeline identifier (e.g. ``eDNA_short``).
        paired: True for paired-end reads, False for single-end.
        demultiplex: True if the pipeline performs demultiplexing (adapters required).
        columns: Required columns, in the order used for the output TSV.
    """

    name: str
    paired: bool
    demultiplex: bool
    columns: tuple[str, ...]

    @property
    def file_columns(self) -> tuple[str, ...]:
        """Return the columns that contain FASTQ paths."""
        return (FILE_FORWARD, FILE_REVERSE) if self.paired else (FILE,)

    @property
    def adapter_columns(self) -> tuple[str, ...]:
        """Return the adapter columns, empty when demultiplexing is already done."""
        return (FORWARD, REVERSE) if self.demultiplex else ()


PIPELINES: dict[str, Pipeline] = {
    p.name: p
    for p in (
        Pipeline(
            "eDNA", True, True, (SAMPLE, CATEGORY, FILE_FORWARD, FILE_REVERSE, FORWARD, REVERSE)
        ),
        Pipeline("eDNA_short", True, False, (SAMPLE, CATEGORY, FILE_FORWARD, FILE_REVERSE)),
        Pipeline("eDNA_single", False, True, (SAMPLE, CATEGORY, FILE, FORWARD, REVERSE)),
        Pipeline("eDNA_single_short", False, False, (SAMPLE, CATEGORY, FILE)),
    )
}


KNOWN_COLUMNS = frozenset(column for p in PIPELINES.values() for column in p.columns)


def similar_name(target: str, candidates: Iterable[str]) -> str | None:
    """Find a header that looks like an expected column name.

    Args:
        target: Expected column name.
        candidates: Header names to search.

    Returns:
        The candidate equal to ``target`` ignoring case, spaces and punctuation, or the
        closest one with a similarity of at least 0.8; None if there is no such header.
    """

    def key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.lower())

    names = list(candidates)
    for name in names:
        if key(name) == key(target):
            return name
    lowered = {name.lower(): name for name in names}
    close = difflib.get_close_matches(target.lower(), list(lowered), n=1, cutoff=0.8)
    return lowered[close[0]] if close else None


def detect_pipeline(columns: Iterable[str]) -> tuple[str, str]:
    """Guess the pipeline from the column names of a table.

    Args:
        columns: Trimmed column names found in the header.

    Returns:
        A tuple ``(pipeline_name, reason)`` where ``reason`` is an Italian sentence
        explaining which columns drove the choice.
    """
    present = list(columns)
    unknown = [column for column in present if column not in KNOWN_COLUMNS]

    def find(name: str) -> str | None:
        # A misspelled header (e.g. "Fowrard") still tells which pipeline was intended.
        return name if name in present else similar_name(name, unknown)

    forward, reverse = find(FORWARD), find(REVERSE)
    single = find(FILE) is not None and find(FILE_FORWARD) is None
    demultiplex = forward is not None and reverse is not None
    if single:
        reads = f"single-end (colonna {FILE} presente, {FILE_FORWARD} assente)"
    else:
        reads = f"paired-end (colonna {FILE} assente oppure {FILE_FORWARD} presente)"
    if demultiplex:
        demux = f"demultiplexing da eseguire (colonne {forward} e {reverse} presenti)"
    else:
        demux = f"demultiplexing già eseguito (colonne {FORWARD} e {REVERSE} non entrambe presenti)"
    name = ("eDNA_single" if single else "eDNA") + ("" if demultiplex else "_short")
    return name, f"{reads}; {demux}"


SEVERITIES = {"E": "error", "W": "warning", "I": "info"}

CODE_TITLES: dict[str, str] = {
    "E00": "File non leggibile o formato non supportato",
    "E01": "Colonna obbligatoria mancante o ripetuta",
    "E02": "Cella vuota in una colonna obbligatoria",
    "E03": "Nome del campione vuoto dopo la normalizzazione",
    "E04": "Campione duplicato",
    "E05": "Percorso non assoluto",
    "E06": "Spazio nel percorso",
    "E07": "FASTQ non compresso",
    "E08": "File forward e reverse identici",
    "E09": "Carattere non valido nell'adattatore",
    "E10": "Combinazione di file e adattatori ripetuta",
    "E11": "Stesso file in più righe",
    "E12": "Tabulazione o a capo dentro una cella",
    "E13": "Nome del campione convertito da Excel in numero o data",
    "E14": "Formula senza valore salvato",
    "W01": "Categoria vuota",
    "W02": "Categorie simili",
    "W03": "Campioni che differiscono solo per maiuscole/minuscole",
    "W04": "Trattino nel percorso",
    "W05": "Carattere non ammesso nel percorso",
    "W06": "Estensione del file non standard",
    "W07": "Cella convertita da Excel in numero o data",
    "I01": "Riepilogo delle categorie",
    "I02": "Colonne extra ignorate",
    "I03": "Nomi dei campioni normalizzati",
    "I04": "Pipeline della scheda",
    "I05": "Scheda saltata",
    "I06": "Nome del file TSV modificato",
}
