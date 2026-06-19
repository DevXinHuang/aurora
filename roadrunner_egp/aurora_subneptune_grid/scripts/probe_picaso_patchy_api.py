#!/usr/bin/env python
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

GRID_ROOT = Path(__file__).resolve().parents[1]
ROADRUNNER_ROOT = GRID_ROOT.parent
REPO_ROOT = ROADRUNNER_ROOT.parent

for path in (GRID_ROOT / "src", ROADRUNNER_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# IMPORTANT: this sets picaso_refdata and PYSYN_CDBS before PICASO import.
import roadrunner.config as cfg  # noqa: F401

print("=== Environment seen by PICASO ===")
print("picaso_refdata =", os.environ.get("picaso_refdata"))
print("PYSYN_CDBS     =", os.environ.get("PYSYN_CDBS"))
print("PICASO_CK_ROOT =", os.environ.get("PICASO_CK_ROOT"))
print()

from picaso import justdoit as jdi

print("=== PICASO import OK ===")
print("justdoit module:", jdi)
print()

def show_signature(obj, name):
    try:
        print(f"{name}{inspect.signature(obj)}")
    except Exception as exc:
        print(f"{name}: signature unavailable: {exc}")

print("=== Constructor signatures ===")
show_signature(jdi.inputs, "jdi.inputs")
try:
    show_signature(jdi.opannection, "jdi.opannection")
except Exception as exc:
    print("jdi.opannection unavailable:", exc)
print()

print("=== Create normal and climate input objects ===")
objects = []
for label, kwargs in [
    ("normal", {}),
    ("climate", {"calculation": "planet", "climate": True}),
]:
    try:
        case = jdi.inputs(**kwargs)
        print(f"{label}: created {type(case)}")
        objects.append((label, case))
    except Exception as exc:
        print(f"{label}: FAILED: {type(exc).__name__}: {exc}")
print()

interesting_tokens = [
    "patch", "cloud", "frac", "cover", "coverage", "f_cloud", "fcloud",
    "hole", "clear", "virga", "climate", "input"
]

for label, case in objects:
    print(f"=== Methods/attrs on {label} case containing patch/cloud/fraction words ===")
    names = sorted(dir(case))
    hits = [
        name for name in names
        if any(tok in name.lower() for tok in interesting_tokens)
    ]
    for name in hits:
        obj = getattr(case, name, None)
        if callable(obj):
            show_signature(obj, f"{label}.{name}")
        else:
            print(f"{label}.{name} = {type(obj).__name__}")
    print()

    print(f"=== Known important method signatures on {label} case ===")
    for name in ["inputs_climate", "climate", "virga", "clouds", "spectrum", "phase_angle", "guillot_pt", "chemeq_visscher_2121"]:
        if hasattr(case, name):
            show_signature(getattr(case, name), f"{label}.{name}")
        else:
            print(f"{label}.{name}: MISSING")
    print()

    print(f"=== Top-level input keys for {label} case ===")
    try:
        print(case.inputs.keys())
        if "climate" in case.inputs:
            print("case.inputs['climate'] keys:", case.inputs["climate"].keys())
        if "clouds" in case.inputs:
            print("case.inputs['clouds'] keys:", case.inputs["clouds"].keys())
        if "atmosphere" in case.inputs:
            print("case.inputs['atmosphere'] keys:", case.inputs["atmosphere"].keys())
    except Exception as exc:
        print("Could not inspect case.inputs:", exc)
    print()
