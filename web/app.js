"use strict";

// Python packages installed in Pyodide at start-up (exact versions).
const PY_REQUIREMENTS = ["openpyxl==3.1.5"];
const INPUT_PATH = "/tmp/edna_input.bin";

const SEVERITIES = [
  ["error", "Errori"],
  ["warning", "Warning"],
  ["info", "Informazioni"],
];

const state = { bytes: null, fileName: "", sheets: [], result: null, confirmed: new Set() };

const $ = (id) => document.getElementById(id);

/** Create an element; text is always set with textContent, never as HTML. */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node[key] = value;
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function setStatus(text, kind = "") {
  const status = $("status");
  status.textContent = text;
  status.className = `status ${kind}`.trim();
}

async function initPython() {
  if (typeof loadPyodide !== "function") {
    throw new Error("Pyodide non è stato scaricato");
  }
  let sources;
  try {
    sources = JSON.parse($("py-sources").textContent);
  } catch {
    throw new Error("pagina non costruita: esegui scripts/build_web.py e apri dist/index.html");
  }
  const py = await loadPyodide();
  py.FS.mkdirTree("/pkg/edna_validator");
  for (const [name, source] of Object.entries(sources)) {
    py.FS.writeFile(`/pkg/edna_validator/${name}`, source);
  }
  await py.loadPackage("micropip");
  py.globals.set("_requirements", py.toPy(PY_REQUIREMENTS));
  await py.runPythonAsync("import micropip\nawait micropip.install(_requirements)");
  py.runPython(
    "import sys\nsys.path.insert(0, '/pkg')\nfrom edna_validator import core, writer"
  );
  return py;
}

const pythonReady = initPython();
pythonReady.then(
  () => setStatus("Validatore pronto: carica una tabella.", "ok"),
  (error) =>
    setStatus(
      "Impossibile preparare il validatore. Serve la connessione a internet al primo " +
        `caricamento: controlla la rete e ricarica la pagina. (Dettaglio: ${error.message})`,
      "error"
    )
);

/** Run a Python expression on the loaded file and parse its JSON result. */
async function callPython(expression, extra = {}) {
  const py = await pythonReady;
  py.FS.writeFile(INPUT_PATH, state.bytes);
  py.globals.set("_filename", state.fileName);
  for (const [name, value] of Object.entries(extra)) py.globals.set(name, value);
  return JSON.parse(py.runPython(expression));
}

/** Pipeline chosen once for the whole file, null until the user answers. */
function selectedPipeline() {
  const checked = document.querySelector('input[name="pipeline"]:checked');
  return checked ? checked.value : null;
}

async function loadFile(file) {
  state.bytes = new Uint8Array(await file.arrayBuffer());
  state.fileName = file.name;
  state.result = null;
  state.confirmed.clear();
  $("file-name").textContent = `File caricato: ${file.name}`;
  $("step-sheets").hidden = true;
  $("step-report").hidden = true;
  $("report").replaceChildren();
  setStatus("Lettura del file…");
  try {
    const info = await callPython(
      `core.inspect_json(open('${INPUT_PATH}', 'rb').read(), _filename)`
    );
    if (info.error) {
      setStatus(`E00 — ${info.error}`, "error");
      return;
    }
    renderSheetChoices(info.sheets);
    setStatus(
      selectedPipeline()
        ? "File letto: controlla le schede e premi «Valida»."
        : "File letto: scegli il tipo di dati al punto 1 e premi «Valida».",
      "ok"
    );
  } catch (error) {
    setStatus(`Errore durante la lettura del file: ${error.message}`, "error");
  }
}

/** Update the per-sheet hints and the Valida button after any change of the choices. */
function refreshChoices() {
  const pipeline = selectedPipeline();
  for (const sheet of state.sheets) {
    if (!sheet.card) continue;
    sheet.card.classList.toggle("disabled", sheet.skip);
    const differs = pipeline !== null && !sheet.skip && sheet.suggested !== pipeline;
    sheet.hint.hidden = !differs;
    sheet.hint.textContent = differs
      ? `Attenzione: dalle colonne questa scheda sembra di tipo ${sheet.suggested} (${sheet.reason}), ` +
        `non ${pipeline}. Controlla la scelta al punto 1 oppure ignora la scheda.`
      : "";
  }
  $("validate").disabled = pipeline === null;
  $("validate-hint").textContent =
    pipeline === null ? "Per validare, scegli prima il tipo di dati al punto 1." : "";
}

function renderSheetChoices(sheets) {
  state.sheets = sheets.map((sheet, index) => ({ ...sheet, index, skip: false }));
  const container = $("sheets");
  container.replaceChildren();
  for (const sheet of state.sheets) {
    const card = el("div", { class: "card" }, el("h3", { text: `Scheda «${sheet.sheet}»` }));
    container.append(card);
    if (sheet.empty) {
      card.append(el("p", { class: "muted", text: "Scheda senza dati: verrà saltata." }));
      continue;
    }
    card.append(
      el("p", {
        class: "muted",
        text: `${sheet.n_rows} righe di dati. Colonne: ${sheet.columns.join(", ") || "nessuna"}.`,
      })
    );
    sheet.card = card;
    sheet.hint = el("p", { class: "hint", hidden: true });
    const skip = el("input", { type: "checkbox" });
    skip.addEventListener("change", () => {
      sheet.skip = skip.checked;
      refreshChoices();
    });
    card.append(
      sheet.hint,
      el("label", { class: "inline" }, skip, " Ignora questa scheda (non è una tabella di campioni)")
    );
  }
  refreshChoices();
  $("step-sheets").hidden = false;
}

async function validate() {
  const pipeline = selectedPipeline();
  if (pipeline === null) {
    refreshChoices();
    return;
  }
  const choices = {};
  for (const sheet of state.sheets) {
    if (!sheet.empty) choices[sheet.sheet] = sheet.skip ? "skip" : pipeline;
  }
  setStatus("Validazione in corso…");
  try {
    state.result = await callPython(
      `core.validate_json(open('${INPUT_PATH}', 'rb').read(), _filename, _choices)`,
      { _choices: JSON.stringify(choices) }
    );
    state.confirmed.clear();
    renderReport();
    setStatus(
      state.result.has_errors
        ? "Validazione completata: ci sono errori da correggere. Dopo la correzione puoi ricaricare il file qui sopra."
        : "Validazione completata senza errori.",
      state.result.has_errors ? "error" : "ok"
    );
    $("step-report").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    setStatus(`Errore durante la validazione: ${error.message}`, "error");
  }
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadableSheets() {
  return state.result.sheets.filter((sheet) => sheet.tsv !== null);
}

function isConfirmed(sheet) {
  return sheet.warnings === 0 || state.confirmed.has(sheet.sheet);
}

async function downloadZip() {
  const files = {};
  for (const sheet of downloadableSheets()) files[sheet.tsv_name] = sheet.tsv;
  const py = await pythonReady;
  py.globals.set("_files", JSON.stringify(files));
  const proxy = py.runPython("import json\nwriter.build_zip(json.loads(_files))");
  const bytes = proxy.toJs();
  proxy.destroy();
  const base = state.fileName.replace(/\.[^.]+$/, "");
  download(`${base}_tsv.zip`, bytes, "application/zip");
}

function summaryTable(result) {
  const head = el("tr");
  for (const title of ["Scheda", "Pipeline", "Campioni", "Errori", "Warning", "Esito"]) {
    head.append(el("th", { text: title }));
  }
  const body = el("tbody");
  for (const sheet of result.sheets) {
    const validated = sheet.status === "validated";
    const kind = !validated ? "info" : sheet.errors ? "error" : sheet.warnings ? "warning" : "ok";
    body.append(
      el(
        "tr",
        {},
        el("td", { text: sheet.sheet }),
        el("td", { text: sheet.pipeline || "—" }),
        el("td", { class: "num", text: validated ? String(sheet.n_samples) : "—" }),
        el("td", { class: "num", text: validated ? String(sheet.errors) : "—" }),
        el("td", { class: "num", text: validated ? String(sheet.warnings) : "—" }),
        el("td", {}, el("span", { class: `badge ${kind}`, text: sheet.outcome }))
      )
    );
  }
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), body));
}

function issueGroups(issues) {
  const nodes = [];
  for (const [severity, label] of SEVERITIES) {
    const selected = issues.filter((issue) => issue.severity === severity);
    if (!selected.length) continue;
    nodes.push(el("p", {}, el("span", { class: `badge ${severity}`, text: `${label}: ${selected.length}` })));
    const codes = [...new Set(selected.map((issue) => issue.code))];
    for (const code of codes) {
      const group = selected.filter((issue) => issue.code === code);
      const list = el("ul");
      for (const issue of group) {
        const where = [];
        if (issue.rows_text) where.push(`${issue.rows.length === 1 ? "Riga" : "Righe"} Excel: ${issue.rows_text}`);
        if (issue.column) where.push(`Colonna: ${issue.column}`);
        list.append(
          el(
            "li",
            {},
            el("div", { text: issue.message }),
            where.length ? el("div", { class: "where", text: where.join(" · ") }) : null
          )
        );
      }
      nodes.push(
        el(
          "details",
          { class: severity, open: severity !== "info" },
          el("summary", { text: `${code} — ${group[0].title} (${group.length})` }),
          list
        )
      );
    }
  }
  return nodes;
}

function sheetCard(sheet, refreshZip) {
  const card = el("div", { class: "card" }, el("h3", { text: `Scheda «${sheet.sheet}»` }));
  card.append(...issueGroups(sheet.issues));
  if (sheet.status !== "validated") return card;

  const actions = el("div", { class: "actions" });
  if (sheet.tsv === null) {
    actions.append(
      el("span", { class: "badge error", text: "TSV non disponibile: correggi gli errori e ricarica il file" })
    );
  } else {
    const button = el("button", { type: "button", text: `Scarica ${sheet.tsv_name}`, disabled: !isConfirmed(sheet) });
    button.addEventListener("click", () =>
      download(sheet.tsv_name, sheet.tsv, "text/tab-separated-values;charset=utf-8")
    );
    if (sheet.warnings > 0) {
      const box = el("input", { type: "checkbox" });
      box.addEventListener("change", () => {
        if (box.checked) state.confirmed.add(sheet.sheet);
        else state.confirmed.delete(sheet.sheet);
        button.disabled = !isConfirmed(sheet);
        refreshZip();
      });
      actions.append(el("label", {}, box, " Ho letto e verificato i warning"));
    }
    actions.append(button);
  }
  card.append(actions);
  return card;
}

function renderReport() {
  const result = state.result;
  const report = $("report");
  report.replaceChildren();

  for (const issue of result.file_issues) {
    report.append(el("p", { class: "file-error", text: `${issue.code} — ${issue.title}: ${issue.message}` }));
  }
  if (result.sheets.length) report.append(summaryTable(result));

  const reportButton = el("button", { type: "button", text: "Scarica il report (.txt)" });
  reportButton.addEventListener("click", () => {
    const base = state.fileName.replace(/\.[^.]+$/, "");
    download(`${base}_report.txt`, result.report_text, "text/plain;charset=utf-8");
  });
  const top = el("div", { class: "actions" }, reportButton);

  let refreshZip = () => {};
  const valid = downloadableSheets();
  if (valid.length > 1) {
    const zipButton = el("button", { type: "button", text: `Scarica tutti i TSV (.zip, ${valid.length} file)` });
    zipButton.addEventListener("click", downloadZip);
    refreshZip = () => {
      zipButton.disabled = !valid.every(isConfirmed);
      zipButton.title = zipButton.disabled ? "Conferma prima i warning di ogni scheda" : "";
    };
    refreshZip();
    top.append(zipButton);
  }
  report.append(top);

  for (const sheet of result.sheets) report.append(sheetCard(sheet, refreshZip));
  $("step-report").hidden = false;
}

function setupInputs() {
  const input = $("file-input");
  const dropzone = $("dropzone");
  input.addEventListener("change", () => {
    if (input.files.length) loadFile(input.files[0]);
    input.value = "";
  });
  for (const type of ["dragenter", "dragover"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add("over");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove("over");
    });
  }
  dropzone.addEventListener("drop", (event) => {
    if (event.dataTransfer.files.length) loadFile(event.dataTransfer.files[0]);
  });
  // Dropping a file outside the drop zone must not make the browser open it.
  for (const type of ["dragover", "drop"]) {
    window.addEventListener(type, (event) => event.preventDefault());
  }
  $("validate").addEventListener("click", validate);
  $("pipeline-choice").addEventListener("change", refreshChoices);
}

setupInputs();
