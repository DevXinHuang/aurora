#!/usr/bin/env python
"""Probe the installed PICASO version for native patchy-cloud climate controls.
Run from the aurora repo inside your picaso4 environment:
  python roadrunner_egp/aurora_subneptune_grid/scripts/probe_picaso_patchy_api.py
"""
from __future__ import annotations

import inspect
import re


def _signature(obj):
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f"<no signature: {exc}>"


def _names(obj, pattern: str):
    rx = re.compile(pattern, re.I)
    out = []
    for name in dir(obj):
        if rx.search(name):
            try:
                attr = getattr(obj, name)
                sig = _signature(attr) if callable(attr) else ""
            except Exception as exc:
                sig = f"<getattr failed: {exc}>"
            out.append((name, sig))
    return out


def main() -> int:
    try:
        import picaso
        from picaso import justdoit as jdi
    except Exception as exc:
        raise SystemExit(f"Could not import PICASO/justdoit: {exc}")

    print("PICASO module:", getattr(picaso, "__file__", "unknown"))
    print("PICASO version attr:", getattr(picaso, "__version__", "unknown"))

    for label, factory in [
        ("plain inputs", lambda: jdi.inputs()),
        ("climate planet inputs", lambda: jdi.inputs(calculation="planet", climate=True)),
    ]:
        print("\n===", label, "===")
        case = factory()
        for method_name in ["inputs_climate", "climate", "virga", "clouds", "phase_angle", "spectrum"]:
            method = getattr(case, method_name, None)
            print(f"{method_name}: {method}")
            if method is not None:
                print(f"  signature: {_signature(method)}")
        print("\nNames containing patch/cloud/frac/cover:")
        for name, sig in _names(case, r"patch|cloud|frac|cover"):
            print(f"  {name}{sig}")
        print("\nTop-level inputs keys:", list(getattr(case, "inputs", {}).keys()))
        try:
            print("atmosphere keys:", list(case.inputs.get("atmosphere", {}).keys()))
        except Exception as exc:
            print("atmosphere key inspection failed:", exc)

    print("\nCopy/paste this whole output back if native patchy is not obvious.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
