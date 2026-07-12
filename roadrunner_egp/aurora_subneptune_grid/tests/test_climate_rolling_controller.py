from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import deque
from pathlib import Path


GRID_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, GRID_ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


controller = load_module("climate_wave_controller", "scripts/submit_climate_wave_controller.py")
chunk_runner = load_module("climate_cache_chunk", "scripts/run_climate_cache_chunk.py")


def test_local_array_ids_never_use_real_climate_indices(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    items = [controller.WorkItem(10000 + index, 10, manifest) for index in range(998)]

    assert controller.local_array_spec(len(items), 999) == "0-997%998"
    mapping = controller.write_index_map(tmp_path, items)
    assert chunk_runner.resolve_climate_group_index(None, str(mapping), 0) == 10000
    assert chunk_runner.resolve_climate_group_index(None, str(mapping), 997) == 10997


def test_available_slots_include_controller_and_interactive_jobs():
    assert controller.available_submit_slots(1000, 1) == 999
    assert controller.available_submit_slots(1000, 2) == 998
    assert controller.available_submit_slots(1000, 1000) == 0


def test_pending_excludes_cached_unsupported_and_in_flight_indices(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    catalog = {index: controller.WorkItem(index, 0, manifest) for index in range(6)}
    runnable = {index: item for index, item in catalog.items() if index not in {1, 4}}

    pending = controller.build_pending_items(runnable, cached_indices={0}, in_flight={2})

    assert [item.climate_group_index for item in pending] == [3, 5]


def test_rolling_refill_takes_only_available_capacity(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    pending = deque(controller.WorkItem(index, 0, manifest) for index in range(998))

    first = controller.take_submission_chunk(pending, capacity=998, max_array_tasks=998)
    assert len(first) == 998

    pending.extend(controller.WorkItem(998 + index, 1, tmp_path / "next.csv") for index in range(998))
    refill = controller.take_submission_chunk(pending, capacity=321, max_array_tasks=998)
    assert len(refill) == 321
    assert len(pending) == 677


def test_retry_schedule_stops_after_configured_attempts(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    output_root = tmp_path / "output"
    submission = controller.ActiveSubmission("123", [controller.WorkItem(42, 0, manifest, attempt=0)])

    retry, failed = controller.retry_or_fail(submission, output_root, max_retries=2)
    assert retry == [controller.WorkItem(42, 0, manifest, attempt=1)]
    assert failed == []

    final = controller.ActiveSubmission("124", [controller.WorkItem(42, 0, manifest, attempt=2)])
    retry, failed = controller.retry_or_fail(final, output_root, max_retries=2)
    assert retry == []
    assert failed == final.items


def test_discovery_maps_active_local_ids_without_duplicates(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    catalog = {10000 + index: controller.WorkItem(10000 + index, 10, manifest) for index in range(3)}
    metadata = {
        "job_id": "123",
        "mapping_path": str(tmp_path / "indices.txt"),
        "indices": [10000, 10001, 10002],
        "waves": [10, 10, 10],
        "attempts": [0, 0, 0],
    }
    (tmp_path / "submission_123.json").write_text(json.dumps(metadata), encoding="utf-8")
    snapshot = [("123", "0", "aurora_clim_w010", "RUNNING"), ("123", "2", "aurora_clim_w010", "PENDING")]

    active = controller.discover_active_submissions(snapshot, catalog, tmp_path)

    assert [item.climate_group_index for item in active["123"].items] == [10000, 10002]


def test_qos_snapshot_uses_array_parent_and_task_ids(monkeypatch, tmp_path: Path):
    seen_command = []

    def fake_run(command, *, cwd, env=None):
        seen_command.extend(command)
        return subprocess.CompletedProcess(command, 0, "123|7|aurora_clim_w010|RUNNING\n", "")

    monkeypatch.setattr(controller, "run", fake_run)

    assert controller.qos_snapshot(tmp_path, "part_qos_standard") == [
        ("123", "7", "aurora_clim_w010", "RUNNING")
    ]
    assert seen_command[-1] == "%F|%K|%j|%T"


def test_retryable_missing_items_do_not_count_as_exhausted_failures(tmp_path: Path):
    manifest = tmp_path / "wave.csv"
    output_root = tmp_path / "output"
    submission = controller.ActiveSubmission(
        "123",
        [controller.WorkItem(index, 0, manifest, attempt=0) for index in range(10)],
    )

    retry, failed = controller.retry_or_fail(submission, output_root, max_retries=2)

    assert len(retry) == 10
    assert failed == []
