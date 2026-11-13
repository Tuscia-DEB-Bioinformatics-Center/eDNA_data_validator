"""Output writers: clean TSV per sheet and zip archive."""

from __future__ import annotations

import io
import zipfile

from .cleaning import normalize_sample
from .models import Dataset
from .schema import CATEGORY, DEFAULT_CATEGORY, SAMPLE, Pipeline


def dataset_to_tsv(dataset: Dataset, pipeline: Pipeline) -> str:
    """Render the clean TSV used as pipeline input.

    Args:
        dataset: Cleaned dataset without errors.
        pipeline: Pipeline that defines columns and their order.

    Returns:
        The TSV text: header, tab separator, ``\\n`` line endings, normalised Sample,
        default category where empty, adapters as provided.
    """
    lines = ["\t".join(pipeline.columns)]
    for row in dataset.rows:
        fields = []
        for column in pipeline.columns:
            value = row.values[column]
            if column == SAMPLE:
                value = normalize_sample(value)
            elif column == CATEGORY and not value:
                value = DEFAULT_CATEGORY
            fields.append(value)
        lines.append("\t".join(fields))
    return "\n".join(lines) + "\n"


def build_zip(files: dict[str, str]) -> bytes:
    """Pack text files into a zip archive.

    Args:
        files: Mapping of file name to text content (encoded as UTF-8 without BOM).

    Returns:
        The bytes of the zip archive.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()
