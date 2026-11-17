# edna-validator

`edna-validator` validates the sample tables that feed the eDNA analysis pipelines, so that
malformed input is caught before a pipeline run is started. It reads an Excel workbook (`.xlsx`,
one dataset per sheet) or a tab-separated file (`.tsv`), reports every problem it finds in a
single pass and, for each valid dataset, generates the clean TSV file that the pipeline expects
as input.

Only the content of the table is checked: the FASTQ files it refers to are never accessed, except by the optional server check (see "Server check" below).

## Features

- Full-table analysis: validation never stops at the first problem; issues are aggregated and
  grouped by sheet, severity and code.
- Three severity levels: **errors** block the generation of the TSV, **warnings** must be
  acknowledged before download, **information** is always shown.
- Automatic cleaning: trimming of every cell, normalisation of sample names, default category.
- Two front-ends on the same engine: a static web page that runs entirely in the browser (the
  file never leaves the computer) and a command-line interface suitable for HPC environments.

The web interface, the command-line help and the validation messages are in Italian.

## Supported pipelines

| Pipeline | Reads | Demultiplexing | Required columns |
|---|---|---|---|
| `eDNA` | paired-end | performed by the pipeline | Sample, Category, File_forward, File_reverse, Forward, Reverse |
| `eDNA_short` | paired-end | already performed | Sample, Category, File_forward, File_reverse |
| `eDNA_single` | single-end | performed by the pipeline | Sample, Category, File, Forward, Reverse |
| `eDNA_single_short` | single-end | already performed | Sample, Category, File |

Column names must match exactly (case included) and the header must be on the first row.
Column order is free and extra columns are ignored.

## Web interface

1. Open the page published on GitHub Pages (or `dist/index.html`, see [Build](#build)).
2. Choose the type of data once: the pipeline applies to every sheet of the file.
3. Drop the file, tick the sheets that are not sample tables so that they are ignored, and press
   **Valida**. A sheet whose columns suggest a different pipeline is highlighted.
4. Read the report. A TSV can be downloaded for every sheet without errors; when a sheet has
   warnings, they must be acknowledged first.

On first load the page downloads Pyodide and `openpyxl`, so an internet connection is required.

## Command line

```bash
pip install -e .
python -m edna_validator table.xlsx --pipeline auto --out out/
```

| Option | Meaning |
|---|---|
| `--pipeline` | Required. `eDNA`, `eDNA_short`, `eDNA_single`, `eDNA_single_short` or `auto` (inferred from the columns). Applies to every sheet. |
| `--sheet NAME=PIPELINE` | Overrides the pipeline for one sheet (repeatable). `NAME=skip` ignores the sheet. |
| `--out DIR` | Writes the report and one TSV per error-free sheet into `DIR`. |
| `--json` | Emits the report as JSON instead of text. |

The exit code is 1 if any error is found and 0 otherwise. From the command line, TSV files are
written even when warnings are present.

The repository includes a valid table that can be used to try the tool:

```bash
python -m edna_validator tests/data/valid_example.tsv --pipeline eDNA
```

### Server check

`controllo-server` checks that the FASTQ files listed in validated TSV files exist on the server.
It only runs on a computer that can see the reads folder (for example through a mapped network
drive over the VPN). The validator itself never accesses the server.

```bash
python -m edna_validator controllo-server out --radice "Z:\reads" --prefisso /archive/project/reads
```

| Option | Meaning |
|---|---|
| `targets` | One or more TSV files, a folder (all `.tsv` files in it) or a pattern such as `out\*.tsv`. |
| `--radice DIR` | Required. Local folder that corresponds to the reads root on the server. |
| `--prefisso PATH` | Start of the server paths to replace with `--radice`. If omitted, the whole path is searched under `--radice`. |
| `--out DIR` | Where to save `controllo_server_report.txt`. Default: the folder of the first file. |

The exit code is 0 if all files are present, 1 if some are missing (E18 or E19) and 2 if the
check cannot run (unreachable folder, unreadable file, wrong arguments).

## Output

One TSV per valid sheet, named after the normalised sheet name. It contains only the columns of
the selected pipeline, in the order listed above, with trimmed values, normalised sample names
and `Uncategorized` where the category is empty. Files are UTF-8 without BOM, tab-separated,
with `\n` line endings.

## Issue codes

Every message in the report carries a code. The table below summarises them; the user manual
describes each one in detail, with examples and the way to fix the table.

| Code | Meaning |
|---|---|
| E00 | Unreadable file or unsupported format |
| E01 | Required column missing or repeated |
| E02 | Empty cell in a required column (other than Category) |
| E03 | Sample empty after normalisation |
| E04 | Duplicated Sample (compared on normalised names) |
| E05 | Path is not absolute |
| E06 | Space in the file name (spaces in folder names are accepted) |
| E07 | Uncompressed FASTQ |
| E08 | File_forward identical to File_reverse |
| E09 | Invalid character in an adapter (only IUPAC nucleotide codes are accepted) |
| E10 | Same combination of files and adapters on several rows (`eDNA`, `eDNA_single`) |
| E11 | Tab or line break inside a cell |
| E12 | Sample stored by the spreadsheet as a number or a date (the original text may be altered, e.g. `1.10` → `1.1`) |
| E13 | Formula without a saved value |
| E14 | Character not allowed in a path (allowed: unaccented letters, digits, `_ - / + .`) |
| E15 | Extension other than `.fq.gz` / `.fastq.gz` |
| E16 | Sheet name that cannot be used for the TSV file: empty after normalisation, or same file name as another sheet |
| E17 | FASTQ listed in a TSV file that does not exist on the server (server check only) |
| E18 | FASTQ path that does not start with the prefix given to the server check (server check only) |
| W01 | Empty Category, replaced by `Uncategorized` |
| W02 | Similar categories |
| W03 | Samples that differ only by letter case |
| W04 | Cell of a column other than Sample stored by the spreadsheet as a number or a date |
| I01 | Category summary |
| I02 | Extra columns ignored |
| I03 | Sample names changed by the normalisation |
| I04 | Pipeline used for the sheet |
| I05 | Sheet skipped |

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format .
```

The engine is pure Python (standard library plus `openpyxl`) and requires Python 3.11 or
later. In the browser it runs on Python 3.12 through Pyodide 0.27.7.

| Path | Content |
|---|---|
| `src/edna_validator/` | Engine: schema, cleaning, readers, rules, report, writer, CLI |
| `web/` | Web interface (plain HTML, CSS and JavaScript) |
| `scripts/build_web.py` | Builds the static site |
| `tests/` | Test suite |
| `tests/data/valid_example.tsv` | Valid reference table (`eDNA` pipeline) from which the tests derive their broken variants |

The workflow `.github/workflows/tests.yml` runs the linter, the format check and the test suite
on every push and pull request, on any branch.

## Build

```bash
python scripts/build_web.py
```

Generates `dist/` with `index.html`, `app.js` and `style.css`. The Python sources of the
package are embedded in `index.html`, so the page also works when opened directly from disk.
To serve it locally:

```bash
python -m http.server --directory dist
```

## Deployment

The workflow `.github/workflows/pages.yml` runs the test suite, builds `dist/` and publishes it
to GitHub Pages on every push to `main`. It must be enabled once in the repository settings:
**Settings → Pages → Source: GitHub Actions**.

## Adding a rule

1. Pick a new code (`E..` error, `W..` warning, `I..` information) and add its title to
   `CODE_TITLES` in `src/edna_validator/schema.py`.
2. In `src/edna_validator/rules.py` write a function that receives the cleaned dataset and the
   pipeline and returns a list of `Issue`:

   ```python
   def double_slash_in_paths(ds: Dataset, pipeline: Pipeline) -> list[Issue]:
       """W08: double slash in a path."""
       groups = _grouped(ds, pipeline.file_columns, lambda value: "//" in value)
       return [
           Issue.create("W08", ds.name, f"Il percorso '{value}' contiene '//'.", rows, column, value)
           for (column, value), rows in groups.items()
       ]
   ```

3. Append the function to the `RULES` list at the bottom of `rules.py`.
4. Add a broken variant to `VARIANTS` in `tests/conftest.py`: the test
   `test_every_rule_code_has_a_variant` fails until the new code is covered.

Thresholds and character sets (category similarity, characters allowed in paths, adapter
alphabet, extensions) are constants in `schema.py`.
