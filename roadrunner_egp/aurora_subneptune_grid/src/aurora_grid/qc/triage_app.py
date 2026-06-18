from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any


DECISION_COLUMNS = ["plot_path", "decision", "rerun_recommended", "notes"]


def load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["plot_path"]: row for row in csv.DictReader(handle)}


def save_decisions(path: Path, decisions: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows(decisions.values())


def run_tk_triage(plot_root: Path, decision_csv: Path, move_bad: bool = False, quarantine_dir: Path | None = None) -> int:
    import tkinter as tk
    from tkinter import simpledialog

    from PIL import Image, ImageTk

    plots = sorted(path for path in plot_root.glob("check_*/*.png"))
    decisions = load_decisions(decision_csv)
    remaining = [path for path in plots if str(path) not in decisions or decisions[str(path)].get("decision") == "skip"]
    if not remaining:
        print("No untriaged plots.")
        return 0

    root = tk.Tk()
    root.title("Aurora QC triage")
    image_label = tk.Label(root)
    image_label.pack()
    status = tk.StringVar()
    tk.Label(root, textvariable=status).pack()
    index = {"value": 0}

    def show_current() -> None:
        path = remaining[index["value"]]
        image = Image.open(path)
        image.thumbnail((1200, 850))
        photo = ImageTk.PhotoImage(image)
        image_label.configure(image=photo)
        image_label.image = photo
        status.set(f"{index['value'] + 1}/{len(remaining)}  {path}")

    def record(decision: str) -> None:
        path = remaining[index["value"]]
        notes = simpledialog.askstring("Notes", "Optional notes:", parent=root) or ""
        decisions[str(path)] = {
            "plot_path": str(path),
            "decision": decision,
            "rerun_recommended": decision == "bad",
            "notes": notes,
        }
        if move_bad and decision == "bad":
            target_dir = quarantine_dir or decision_csv.parent / "quarantine"
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target_dir / path.name))
        save_decisions(decision_csv, decisions)
        index["value"] += 1
        if index["value"] >= len(remaining):
            root.destroy()
        else:
            show_current()

    buttons = tk.Frame(root)
    buttons.pack()
    tk.Button(buttons, text="Good", command=lambda: record("good")).pack(side=tk.LEFT)
    tk.Button(buttons, text="Bad", command=lambda: record("bad")).pack(side=tk.LEFT)
    tk.Button(buttons, text="Skip", command=lambda: record("skip")).pack(side=tk.LEFT)

    show_current()
    root.mainloop()
    return 0
