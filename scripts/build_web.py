"""Build the static site in ``dist/`` with the Python package embedded in the page.

``fetch()`` of local files fails under ``file://``, so the sources of ``edna_validator``
are stored as JSON inside ``dist/index.html`` and written to Pyodide's filesystem by
``app.js``. The same ``dist/`` folder is published on GitHub Pages.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "edna_validator"
WEB = ROOT / "web"
DIST = ROOT / "dist"
PLACEHOLDER = "__PY_SOURCES__"
ASSETS = ("app.js", "style.css")
# Modules not needed in the browser.
EXCLUDED = {"__main__.py"}


def build() -> Path:
    """Generate ``dist/`` from ``web/`` and the Python package.

    Returns:
        The path of the generated ``index.html``.
    """
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
        if path.name not in EXCLUDED
    }
    # "</" must not appear inside a <script> element.
    embedded = json.dumps(sources, ensure_ascii=False).replace("</", "<\\/")

    template = (WEB / "index.html").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {PLACEHOLDER} not found in web/index.html")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    index = DIST / "index.html"
    page = template.replace(PLACEHOLDER, embedded)
    for name in ASSETS:
        # A version derived from the content makes browsers fetch the file again when it
        # changes, instead of reusing a cached copy next to a newer page.
        digest = hashlib.sha256((WEB / name).read_bytes()).hexdigest()[:10]
        reference = f'"{name}"'
        if reference not in page:
            raise SystemExit(f"Reference to {name} not found in web/index.html")
        page = page.replace(reference, f'"{name}?v={digest}"')
        shutil.copyfile(WEB / name, DIST / name)
    index.write_text(page, encoding="utf-8", newline="\n")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    return index


if __name__ == "__main__":
    print(f"Built {build()}")
