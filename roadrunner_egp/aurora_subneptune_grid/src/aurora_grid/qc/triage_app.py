from __future__ import annotations

import csv
import json
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DECISION_COLUMNS = [
    "plot_path",
    "decision",
    "rerun_recommended",
    "notes",
    "timestamp",
    "run_id",
    "check",
]


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AURORA QC Triage</title>
<style>
:root { --bg:#0d1117; --panel:#161b22; --line:#30363d; --text:#e6edf3; --muted:#8b949e; --good:#3fb950; --bad:#f85149; --skip:#d29922; --accent:#58a6ff; }
* { box-sizing: border-box; }
body { margin:0; height:100vh; display:flex; flex-direction:column; overflow:hidden; background:var(--bg); color:var(--text); font-family:system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
header, footer { flex:0 0 auto; display:flex; align-items:center; gap:12px; padding:10px 16px; background:var(--panel); border-color:var(--line); }
header { border-bottom:1px solid var(--line); }
footer { border-top:1px solid var(--line); justify-content:center; position:relative; }
select, input { background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:6px; padding:7px 9px; }
a { color:var(--accent); text-decoration:none; }
button { border:2px solid; border-radius:7px; padding:9px 24px; font-weight:700; background:transparent; cursor:pointer; }
.good { color:var(--good); border-color:var(--good); }
.bad { color:var(--bad); border-color:var(--bad); }
.skip { color:var(--skip); border-color:var(--skip); }
.undo { color:var(--muted); border-color:var(--line); }
#stats { display:flex; gap:14px; color:var(--muted); font-size:13px; }
#progress { margin-left:auto; color:var(--muted); font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
#links { display:flex; gap:10px; font-size:12px; }
#name { flex:0 0 auto; padding:8px 16px; color:var(--accent); font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; border-bottom:1px solid var(--line); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#wrap { flex:1 1 auto; min-height:0; display:flex; align-items:center; justify-content:center; padding:12px; }
#plot { max-width:100%; max-height:100%; object-fit:contain; border:1px solid var(--line); border-radius:4px; background:white; }
#empty { display:none; color:var(--muted); text-align:center; line-height:1.5; }
#flash { position:fixed; left:50%; top:50%; transform:translate(-50%,-50%); opacity:0; transition:opacity .12s; padding:14px 34px; border-radius:10px; background:var(--panel); font-size:42px; font-weight:800; pointer-events:none; }
#flash.show { opacity:.96; }
#hint { position:absolute; right:16px; color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<header>
  <label>Check</label><select id="folder"></select>
  <div id="stats"><span>Good <b id="good">0</b></span><span>Bad <b id="bad">0</b></span><span>Skip <b id="skip">0</b></span></div>
  <div id="links"></div>
  <div id="progress">0 / 0</div>
</header>
<div id="name">Loading...</div>
<main id="wrap">
  <img id="plot" alt="diagnostic plot">
  <div id="empty">No untriaged plots in this check folder.</div>
</main>
<footer>
  <button class="good" onclick="decide('good')">Good G</button>
  <button class="bad" onclick="decide('bad')">Bad B</button>
  <button class="skip" onclick="decide('skip')">Skip S</button>
  <button class="undo" onclick="undo()">Undo U</button>
  <span id="hint">keyboard: G / B / S / U</span>
</footer>
<div id="flash"></div>
<script>
let state = { folder: "", models: [], undecided: [], idx: 0, history: [] };

async function getJSON(url, opts) {
  const response = await fetch(url, opts);
  if (!response.ok) throw new Error(await response.text());
  return await response.json();
}

async function init() {
  const config = await getJSON("/api/config");
  const links = document.getElementById("links");
  links.innerHTML = config.links.map(link => `<a href="${link.url}" target="_blank">${link.label}</a>`).join("");
  const folders = await getJSON("/api/folders");
  const select = document.getElementById("folder");
  select.innerHTML = folders.map(name => `<option value="${name}">${name}</option>`).join("");
  select.onchange = () => loadFolder(select.value);
  if (folders.length) {
    select.value = folders[0];
    await loadFolder(folders[0]);
  } else {
    showEmpty("No check folders found under the plot root.");
  }
}

async function loadFolder(folder) {
  state.folder = folder;
  state.history = [];
  const data = await getJSON(`/api/models?folder=${encodeURIComponent(folder)}`);
  state.models = data.models;
  refreshUndecided();
  showCurrent();
  updateStats();
}

function refreshUndecided() {
  state.undecided = state.models.map((_, i) => i).filter(i => !state.models[i].decision || state.models[i].decision === "skip");
  state.idx = Math.min(state.idx, Math.max(0, state.undecided.length - 1));
}

function currentModel() {
  if (!state.undecided.length) return null;
  return state.models[state.undecided[state.idx]];
}

function showEmpty(message) {
  document.getElementById("plot").style.display = "none";
  const empty = document.getElementById("empty");
  empty.style.display = "block";
  empty.textContent = message;
  document.getElementById("name").textContent = message;
}

function showCurrent() {
  const model = currentModel();
  if (!model) {
    showEmpty("No untriaged plots in this check folder.");
    updateProgress();
    return;
  }
  const image = document.getElementById("plot");
  image.style.display = "block";
  document.getElementById("empty").style.display = "none";
  image.src = `/api/plot?path=${encodeURIComponent(model.diagnostic_plot_path)}&t=${Date.now()}`;
  const spectrum = model.spectrum_plot_path ? ` | <a href="/api/plot?path=${encodeURIComponent(model.spectrum_plot_path)}" target="_blank">spectrum</a>` : "";
  document.getElementById("name").innerHTML = `${model.run_id} <span style="color:var(--muted)">(${model.check})</span>${spectrum}`;
  updateProgress();
}

function updateProgress() {
  const decided = state.models.filter(m => m.decision && m.decision !== "skip").length;
  document.getElementById("progress").textContent = `${state.undecided.length ? state.idx + 1 : 0}/${state.undecided.length} undecided (${decided}/${state.models.length} decided)`;
}

function updateStats() {
  document.getElementById("good").textContent = state.models.filter(m => m.decision === "good").length;
  document.getElementById("bad").textContent = state.models.filter(m => m.decision === "bad").length;
  document.getElementById("skip").textContent = state.models.filter(m => m.decision === "skip").length;
}

function flash(decision) {
  const el = document.getElementById("flash");
  el.className = `show ${decision}`;
  el.textContent = decision === "good" ? "GOOD" : decision === "bad" ? "BAD" : "SKIP";
  setTimeout(() => { el.className = ""; }, 350);
}

async function decide(decision) {
  const model = currentModel();
  if (!model) return;
  state.history.push({ plot_path: model.diagnostic_plot_path, previous: model.decision || "" });
  const notes = "";
  await getJSON("/api/decide", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ plot_path: model.diagnostic_plot_path, decision, notes })
  });
  model.decision = decision;
  flash(decision);
  updateStats();
  refreshUndecided();
  showCurrent();
}

async function undo() {
  const last = state.history.pop();
  if (!last) return;
  await getJSON("/api/undo", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ plot_path: last.plot_path })
  });
  const model = state.models.find(m => m.diagnostic_plot_path === last.plot_path);
  if (model) model.decision = last.previous || "";
  updateStats();
  refreshUndecided();
  const pos = state.undecided.findIndex(i => state.models[i].diagnostic_plot_path === last.plot_path);
  if (pos >= 0) state.idx = pos;
  showCurrent();
}

document.addEventListener("keydown", event => {
  if (event.target.tagName === "SELECT" || event.target.tagName === "INPUT") return;
  const key = event.key.toLowerCase();
  if (key === "g") decide("good");
  if (key === "b") decide("bad");
  if (key === "s") decide("skip");
  if (key === "u" || (event.ctrlKey && key === "z")) { event.preventDefault(); undo(); }
});

init().catch(error => showEmpty(error.message));
</script>
</body>
</html>
"""


def _normalise_decision_row(row: dict[str, Any]) -> dict[str, Any]:
    return {column: str(row.get(column, "")) for column in DECISION_COLUMNS}


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [_normalise_decision_row(row) for row in csv.DictReader(handle)]
    return {row["plot_path"]: row for row in rows if row.get("plot_path")}


def save_decisions(path: Path, decisions: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_normalise_decision_row(row) for row in decisions.values()]
    rows.sort(key=lambda row: row.get("plot_path", ""))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_plot_path(plot_root: Path, requested: str) -> Path | None:
    if not requested:
        return None
    root = plot_root.resolve()
    raw_path = Path(requested)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        resolved = candidate.resolve()
    except Exception:
        return None
    if not _is_relative_to(resolved, root):
        return None
    return resolved


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _run_id_from_plot(path: str) -> str:
    stem = Path(path).stem
    for suffix in ("_diagnostic", "_spectrum"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def discover_plot_folders(plot_root: Path) -> list[str]:
    root = plot_root.resolve()
    if not root.exists():
        return []
    folders = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and path.name.startswith("check_") and any(path.glob("*.png")):
            folders.append(path.name)
    return folders


def _decision_for(decisions: dict[str, dict[str, Any]], rel_path: str, abs_path: Path) -> dict[str, Any]:
    return decisions.get(rel_path) or decisions.get(str(abs_path)) or {}


def discover_models(plot_root: Path, folder: str, decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if folder not in discover_plot_folders(plot_root):
        return []
    root = plot_root.resolve()
    folder_path = safe_plot_path(root, folder)
    if folder_path is None or not folder_path.is_dir():
        return []
    diagnostic_plots = sorted(folder_path.glob("*_diagnostic.png"))
    if not diagnostic_plots:
        diagnostic_plots = [path for path in sorted(folder_path.glob("*.png")) if not path.name.endswith("_spectrum.png")]

    models: list[dict[str, Any]] = []
    for diagnostic in diagnostic_plots:
        rel_diag = _relative_path(diagnostic, root)
        run_id = _run_id_from_plot(rel_diag)
        spectrum = diagnostic.with_name(f"{run_id}_spectrum.png")
        rel_spectrum = _relative_path(spectrum, root) if spectrum.exists() else ""
        decision = _decision_for(decisions, rel_diag, diagnostic)
        models.append(
            {
                "run_id": run_id,
                "check": folder,
                "diagnostic_plot_path": rel_diag,
                "spectrum_plot_path": rel_spectrum,
                "decision": decision.get("decision", ""),
                "notes": decision.get("notes", ""),
            }
        )
    return models


def record_decision(
    plot_root: Path,
    decision_csv: Path,
    decisions: dict[str, dict[str, Any]],
    plot_path: str,
    decision: str,
    notes: str = "",
) -> dict[str, Any]:
    decision = decision.lower()
    if decision not in {"good", "bad", "skip"}:
        raise ValueError("invalid decision")
    path = safe_plot_path(plot_root, plot_path)
    if path is None or not path.exists() or path.suffix.lower() != ".png":
        raise ValueError("invalid plot path")
    rel_path = _relative_path(path, plot_root)
    row = {
        "plot_path": rel_path,
        "decision": decision,
        "rerun_recommended": str(decision == "bad"),
        "notes": notes,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": _run_id_from_plot(rel_path),
        "check": rel_path.split("/", 1)[0],
    }
    decisions[rel_path] = row
    save_decisions(decision_csv, decisions)
    return row


def undo_decision(
    plot_root: Path,
    decision_csv: Path,
    decisions: dict[str, dict[str, Any]],
    plot_path: str,
) -> None:
    path = safe_plot_path(plot_root, plot_path)
    rel_path = _relative_path(path, plot_root) if path is not None else plot_path
    decisions.pop(rel_path, None)
    if path is not None:
        decisions.pop(str(path), None)
    save_decisions(decision_csv, decisions)


class _TriageServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        plot_root: Path,
        decision_csv: Path,
        qc_summary: Path | None = None,
        qc_flags: Path | None = None,
    ) -> None:
        super().__init__(server_address, _TriageHandler)
        self.plot_root = plot_root.resolve()
        self.decision_csv = decision_csv
        self.qc_summary = qc_summary
        self.qc_flags = qc_flags
        self.decisions = load_decisions(decision_csv)


class _TriageHandler(BaseHTTPRequestHandler):
    server: _TriageServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/html; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str) -> None:
        payload = path.read_bytes()
        self.send_response(int(HTTPStatus.OK))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            self._send_text(HTML)
            return
        if parsed.path == "/api/config":
            links = [{"label": "triage_decisions.csv", "url": "/api/csv?kind=decisions"}]
            if self.server.qc_summary is not None:
                links.append({"label": "qc_summary.csv", "url": "/api/csv?kind=summary"})
            if self.server.qc_flags is not None:
                links.append({"label": "qc_flags.csv", "url": "/api/csv?kind=flags"})
            self._send_json({"links": links})
            return
        if parsed.path == "/api/folders":
            self._send_json(discover_plot_folders(self.server.plot_root))
            return
        if parsed.path == "/api/models":
            folder = params.get("folder", [""])[0]
            self._send_json({"folder": folder, "models": discover_models(self.server.plot_root, folder, self.server.decisions)})
            return
        if parsed.path == "/api/plot":
            requested = params.get("path", [""])[0]
            path = safe_plot_path(self.server.plot_root, requested)
            if path is None or not path.exists() or path.suffix.lower() != ".png":
                self._send_text("not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            self._send_file(path, "image/png")
            return
        if parsed.path == "/api/csv":
            kind = params.get("kind", [""])[0]
            paths = {
                "decisions": self.server.decision_csv,
                "summary": self.server.qc_summary,
                "flags": self.server.qc_flags,
            }
            path = paths.get(kind)
            if path is None or not path.exists():
                self._send_text("not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                return
            self._send_file(path, "text/csv; charset=utf-8")
            return
        self._send_text("not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            data = self._read_json()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/decide":
            self._handle_decide(data)
            return
        if parsed.path == "/api/undo":
            self._handle_undo(data)
            return
        self._send_text("not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    def _handle_decide(self, data: dict[str, Any]) -> None:
        try:
            row = record_decision(
                self.server.plot_root,
                self.server.decision_csv,
                self.server.decisions,
                str(data.get("plot_path", "")),
                str(data.get("decision", "")),
                str(data.get("notes", "")),
            )
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "decision": row})

    def _handle_undo(self, data: dict[str, Any]) -> None:
        undo_decision(
            self.server.plot_root,
            self.server.decision_csv,
            self.server.decisions,
            str(data.get("plot_path", "")),
        )
        self._send_json({"ok": True})


def run_browser_triage(
    plot_root: Path,
    decision_csv: Path,
    qc_summary: Path | None = None,
    qc_flags: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    plot_root = plot_root.resolve()
    decision_csv.parent.mkdir(parents=True, exist_ok=True)
    server = _TriageServer((host, port), plot_root, decision_csv, qc_summary=qc_summary, qc_flags=qc_flags)
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"triage_url: {url}")
    print(f"plot_root: {plot_root}")
    print(f"triage_decisions: {decision_csv}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ntriage server stopped")
    finally:
        server.server_close()
    return 0


def run_tk_triage(
    plot_root: Path,
    decision_csv: Path,
    move_bad: bool = False,
    quarantine_dir: Path | None = None,
) -> int:
    return run_browser_triage(plot_root, decision_csv)
