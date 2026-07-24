#!/usr/bin/env python
"""Autonomously keep Aurora climate-cache work in the Slurm queue."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np


WAVE_RE = re.compile(r"climate_wave_(?P<wave>\d+)_(?P<start>\d+)_(?P<end>\d+)\.csv$")


@dataclass(frozen=True)
class WorkItem:
    climate_group_index: int
    wave: int
    manifest: Path
    attempt: int = 0
    climate_group_key: str = ""


@dataclass
class ActiveSubmission:
    job_id: str
    items: list[WorkItem]
    mapping_path: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous Aurora climate submitter.")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--wave-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--model", default="aurora_subneptune_v1_dhuang")
    parser.add_argument("--slurm-script", default="roadrunner_egp/aurora_subneptune_grid/slurm/run_climate_cache.slurm")
    parser.add_argument("--mode", choices=("sequential", "rolling"), default="sequential")
    parser.add_argument("--start-wave", type=int, default=0)
    parser.add_argument("--end-wave", type=int, default=39)
    parser.add_argument("--throttle", type=int, default=999)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--post-wave-sleep-seconds", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-array-tasks", type=int, default=998)
    parser.add_argument("--stop-failure-fraction", type=float, default=0.50)
    parser.add_argument("--submit-retry-seconds", type=int, default=60)
    parser.add_argument("--adopt-first-job-id", default="")
    parser.add_argument("--qos", default="part_qos_standard")
    parser.add_argument("--qos-submit-limit", type=int, default=1000)
    parser.add_argument("--time-limits", default="02:00:00,03:00:00,04:00:00")
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--task-log-dir", default="")
    parser.add_argument("--failed-indices-path", required=True)
    parser.add_argument("--skip-indices-path", default="")
    parser.add_argument("--submission-dir", default="")
    return parser.parse_args()


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str, log_path: Path) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def wave_file(wave_dir: Path, wave: int) -> tuple[Path, int, int]:
    matches = sorted(wave_dir.glob(f"climate_wave_{wave:03d}_*.csv"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one manifest for wave {wave:03d}, found {len(matches)}.")
    match = WAVE_RE.match(matches[0].name)
    if not match:
        raise ValueError(f"Unexpected wave manifest name: {matches[0]}")
    return matches[0], int(match.group("start")), int(match.group("end"))


def read_wave_rows(path: Path) -> list[tuple[int, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "climate_group_key" not in reader.fieldnames:
            raise ValueError(
                f"Stale wave manifest {path}: missing climate_group_key. Regenerate climate waves."
            )
        rows = []
        for row in reader:
            key = str(row.get("climate_group_key", "")).strip()
            if not key:
                raise ValueError(f"Stale wave manifest {path}: empty climate_group_key.")
            rows.append((int(row["climate_group_index"]), key))
        return rows


def read_skip_indices(path: Path | None) -> set[int]:
    if path is None or not path.exists():
        return set()
    with path.open(newline="") as handle:
        return {
            int(row["climate_group_index"])
            for row in csv.DictReader(handle)
            if row.get("climate_group_index") not in (None, "")
        }


def cache_path(output_root: Path, climate_group_index: int) -> Path:
    return output_root / "climate_cache" / f"climate_{int(climate_group_index):02d}.npz"


def cache_matches(output_root: Path, item: WorkItem) -> bool:
    path = cache_path(output_root, item.climate_group_index)
    if not path.exists() or path.stat().st_size <= 0:
        return False
    if not item.climate_group_key:
        return False
    try:
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data["metadata_json"]))
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return False
    return str(metadata.get("climate_group_key", "")) == item.climate_group_key


def build_catalog(wave_dir: Path, start_wave: int, end_wave: int) -> dict[int, WorkItem]:
    catalog: dict[int, WorkItem] = {}
    for wave in range(start_wave, end_wave + 1):
        manifest, _, _ = wave_file(wave_dir, wave)
        for index, climate_key in read_wave_rows(manifest):
            if index in catalog:
                raise ValueError(f"Duplicate climate_group_index across wave manifests: {index}")
            catalog[index] = WorkItem(index, wave, manifest, climate_group_key=climate_key)
    return catalog


def build_pending_items(
    runnable: dict[int, WorkItem],
    cached_indices: set[int],
    in_flight: set[int],
) -> deque[WorkItem]:
    return deque(
        item
        for index, item in sorted(runnable.items())
        if index not in cached_indices and index not in in_flight
    )


def available_submit_slots(qos_limit: int, active_qos_jobs: int) -> int:
    return max(0, int(qos_limit) - int(active_qos_jobs))


def local_array_spec(task_count: int, throttle: int) -> str:
    if task_count < 1:
        raise ValueError("Cannot build a Slurm array for zero tasks.")
    return f"0-{task_count - 1}%{min(task_count, int(throttle))}"


def take_submission_chunk(
    pending: deque[WorkItem],
    capacity: int,
    max_array_tasks: int,
) -> list[WorkItem]:
    if not pending or capacity <= 0:
        return []
    first = pending.popleft()
    chunk = [first]
    limit = min(int(capacity), int(max_array_tasks))
    while pending and len(chunk) < limit:
        candidate = pending[0]
        if candidate.manifest != first.manifest or candidate.attempt != first.attempt:
            break
        chunk.append(pending.popleft())
    return chunk


def restore_submission_chunk(pending: deque[WorkItem], chunk: list[WorkItem]) -> None:
    pending.extendleft(reversed(chunk))


def write_state(path: Path, **state: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": now(), **state}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_index_map(submission_dir: Path, items: list[WorkItem]) -> Path:
    submission_dir.mkdir(parents=True, exist_ok=True)
    path = submission_dir / f"indices_w{items[0].wave:03d}_a{items[0].attempt}_{os.getpid()}_{time.time_ns()}.txt"
    path.write_text("".join(f"{item.climate_group_index}\n" for item in items), encoding="utf-8")
    return path


def write_submission_metadata(submission_dir: Path, submission: ActiveSubmission) -> None:
    metadata = {
        "job_id": submission.job_id,
        "mapping_path": str(submission.mapping_path) if submission.mapping_path else None,
        "indices": [item.climate_group_index for item in submission.items],
        "waves": [item.wave for item in submission.items],
        "attempts": [item.attempt for item in submission.items],
    }
    (submission_dir / f"submission_{submission.job_id}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def submit_array(
    *,
    repo_root: Path,
    slurm_script: Path,
    model: str,
    items: list[WorkItem],
    throttle: int,
    time_limit: str,
    submission_dir: Path,
    log_path: Path,
    task_log_dir: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = run,
) -> ActiveSubmission | None:
    mapping_path = write_index_map(submission_dir, items)
    array_spec = local_array_spec(len(items), throttle)
    env = os.environ.copy()
    env.update({"MODEL": model, "MANIFEST": str(items[0].manifest), "CLIMATE_INDEX_MAP": str(mapping_path)})
    cmd = [
        "sbatch",
        "--parsable",
        f"--array={array_spec}",
        f"--job-name=aurora_clim_w{items[0].wave:03d}",
        f"--time={time_limit}",
        f"--output={task_log_dir}/%x_%A_%a.out",
        f"--error={task_log_dir}/%x_%A_%a.err",
        "--export=ALL,MODEL,MANIFEST,CLIMATE_INDEX_MAP",
        str(slurm_script),
    ]
    log(
        f"submitting wave={items[0].wave:03d} attempt={items[0].attempt} "
        f"tasks={len(items)} local_array={array_spec} time={time_limit}",
        log_path,
    )
    result = run_command(cmd, cwd=repo_root, env=env)
    if result.returncode != 0:
        log(
            f"submit failed rc={result.returncode} stdout={result.stdout.strip()!r} "
            f"stderr={result.stderr.strip()!r}",
            log_path,
        )
        return None
    job_id = result.stdout.strip().splitlines()[-1].strip().split(";")[0]
    submission = ActiveSubmission(job_id, items, mapping_path)
    write_submission_metadata(submission_dir, submission)
    log(f"submitted job_id={job_id} tasks={len(items)} map={mapping_path}", log_path)
    return submission


def qos_snapshot(repo_root: Path, qos: str) -> list[tuple[str, str, str, str]]:
    result = run(
        ["squeue", "-h", "-r", "-u", os.environ.get("USER", ""), "-q", qos, "-o", "%F|%K|%j|%T"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise RuntimeError(f"squeue failed: {result.stderr.strip()}")
    rows: list[tuple[str, str, str, str]] = []
    for line in result.stdout.splitlines():
        fields = line.strip().split("|", 3)
        if len(fields) == 4:
            rows.append((fields[0], fields[1], fields[2], fields[3]))
    return rows


def load_submission_metadata(submission_dir: Path) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for path in submission_dir.glob("submission_*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        job_id = str(value.get("job_id", ""))
        if job_id:
            metadata[job_id] = value
    return metadata


def discover_active_submissions(
    snapshot: list[tuple[str, str, str, str]],
    catalog: dict[int, WorkItem],
    submission_dir: Path,
) -> dict[str, ActiveSubmission]:
    by_job: dict[str, list[int]] = {}
    for job_id, task_id, job_name, _state in snapshot:
        if job_name.startswith("aurora_clim") and task_id.isdigit():
            by_job.setdefault(job_id, []).append(int(task_id))

    saved = load_submission_metadata(submission_dir)
    active: dict[str, ActiveSubmission] = {}
    for job_id, task_ids in by_job.items():
        record = saved.get(job_id)
        items: list[WorkItem] = []
        mapping_path: Path | None = None
        if record:
            indices = [int(value) for value in record.get("indices", [])]
            waves = [int(value) for value in record.get("waves", [])]
            attempts = [int(value) for value in record.get("attempts", [])]
            for local_id in task_ids:
                if local_id < len(indices):
                    base = catalog.get(indices[local_id])
                    if base:
                        items.append(
                            WorkItem(
                                base.climate_group_index,
                                waves[local_id],
                                base.manifest,
                                attempts[local_id],
                                base.climate_group_key,
                            )
                        )
            raw_mapping = record.get("mapping_path")
            if raw_mapping:
                mapping_path = Path(str(raw_mapping))
        else:
            # Legacy arrays used the real climate index as the Slurm task ID.
            items = [catalog[index] for index in task_ids if index in catalog]
        if items:
            active[job_id] = ActiveSubmission(job_id, items, mapping_path)
    return active


def append_failures(path: Path, items: list[WorkItem]) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(f"{item.wave:03d},{item.climate_group_index},{item.attempt}\n")


def retry_or_fail(
    submission: ActiveSubmission,
    output_root: Path,
    max_retries: int,
) -> tuple[list[WorkItem], list[WorkItem]]:
    retry: list[WorkItem] = []
    failed: list[WorkItem] = []
    for item in submission.items:
        if cache_matches(output_root, item):
            continue
        if item.attempt < max_retries:
            retry.append(
                WorkItem(
                    item.climate_group_index,
                    item.wave,
                    item.manifest,
                    item.attempt + 1,
                    item.climate_group_key,
                )
            )
        else:
            failed.append(item)
    return retry, failed


def run_controller(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    wave_dir = Path(args.wave_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    slurm_script = (repo_root / args.slurm_script).resolve()
    state_path = Path(args.state_path).expanduser().resolve()
    log_path = Path(args.log_path).expanduser().resolve()
    failed_path = Path(args.failed_indices_path).expanduser().resolve()
    task_log_dir = (
        Path(args.task_log_dir).expanduser().resolve()
        if args.task_log_dir
        else output_root / "logs"
    )
    skip_path = Path(args.skip_indices_path).expanduser().resolve() if args.skip_indices_path else None
    submission_dir = (
        Path(args.submission_dir).expanduser().resolve()
        if args.submission_dir
        else state_path.parent / "submissions"
    )
    submission_dir.mkdir(parents=True, exist_ok=True)
    task_log_dir.mkdir(parents=True, exist_ok=True)
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    failed_path.touch(exist_ok=True)

    time_limits = [value.strip() for value in args.time_limits.split(",") if value.strip()]
    if len(time_limits) <= args.max_retries:
        raise ValueError("--time-limits must provide one value for every attempt.")

    catalog = build_catalog(wave_dir, args.start_wave, args.end_wave)
    skip_indices = read_skip_indices(skip_path)
    runnable = {index: item for index, item in catalog.items() if index not in skip_indices}
    snapshot = qos_snapshot(repo_root, args.qos)
    active = discover_active_submissions(snapshot, catalog, submission_dir)
    in_flight = {item.climate_group_index for submission in active.values() for item in submission.items}
    cached_indices = {
        index for index, item in runnable.items() if cache_matches(output_root, item)
    }
    pending = build_pending_items(runnable, cached_indices, in_flight)

    initial_cache_count = len(cached_indices)
    started = time.monotonic()
    submitted_total = 0
    failed_total = 0
    absent_since: dict[str, float] = {}
    log(
        f"controller start mode={args.mode} waves={args.start_wave:03d}-{args.end_wave:03d} "
        f"runnable={len(runnable)} cached={initial_cache_count} pending={len(pending)} "
        f"adopted_jobs={len(active)} qos_limit={args.qos_submit_limit}",
        log_path,
    )

    while pending or active:
        snapshot = qos_snapshot(repo_root, args.qos)
        active_job_ids = {row[0] for row in snapshot}
        for job_id in list(active):
            if job_id in active_job_ids:
                absent_since.pop(job_id, None)
                continue
            first_absent = absent_since.setdefault(job_id, time.monotonic())
            if time.monotonic() - first_absent < args.post_wave_sleep_seconds:
                continue
            absent_since.pop(job_id, None)
            submission = active.pop(job_id)
            retry, failed = retry_or_fail(submission, output_root, args.max_retries)
            cached_indices.update(
                item.climate_group_index
                for item in submission.items
                if cache_matches(output_root, item)
            )
            if retry:
                pending.extend(retry)
            if failed:
                append_failures(failed_path, failed)
                failed_total += len(failed)
            failed_fraction = len(failed) / max(1, len(submission.items))
            log(
                f"job complete job_id={job_id} tasks={len(submission.items)} "
                f"retry={len(retry)} failed={len(failed)}",
                log_path,
            )
            if failed_fraction >= args.stop_failure_fraction:
                write_state(
                    state_path,
                    status="stopped_large_failure",
                    job_id=job_id,
                    failed_fraction=failed_fraction,
                    retry_count=len(retry),
                    failed_count=len(failed),
                )
                return 2

        active_qos_jobs = len(snapshot)
        capacity = available_submit_slots(args.qos_submit_limit, active_qos_jobs)
        if args.mode == "sequential" and active:
            capacity = 0

        while pending and capacity > 0:
            chunk = take_submission_chunk(pending, capacity, args.max_array_tasks)
            if not chunk:
                break
            submission = submit_array(
                repo_root=repo_root,
                slurm_script=slurm_script,
                model=args.model,
                items=chunk,
                throttle=args.throttle,
                time_limit=time_limits[chunk[0].attempt],
                submission_dir=submission_dir,
                log_path=log_path,
                task_log_dir=task_log_dir,
            )
            if submission is None:
                restore_submission_chunk(pending, chunk)
                break
            active[submission.job_id] = submission
            submitted_total += len(chunk)
            capacity -= len(chunk)
            if args.mode == "sequential":
                break

        cache_count = len(cached_indices)
        elapsed_hours = max((time.monotonic() - started) / 3600, 1 / 3600)
        throughput = max(0.0, cache_count - initial_cache_count) / elapsed_hours
        remaining = max(0, len(runnable) - cache_count - failed_total)
        eta_hours = remaining / throughput if throughput > 0 else None
        running = sum(1 for row in snapshot if row[2].startswith("aurora_clim") and row[3] == "RUNNING")
        queued = sum(1 for row in snapshot if row[2].startswith("aurora_clim") and row[3] != "RUNNING")
        write_state(
            state_path,
            status="rolling" if args.mode == "rolling" else "sequential",
            cached_count=cache_count,
            runnable_count=len(runnable),
            skipped_count=len(skip_indices),
            pending_count=len(pending),
            active_submission_count=len(active),
            running_climate_tasks=running,
            queued_climate_tasks=queued,
            active_qos_jobs=active_qos_jobs,
            qos_submit_limit=args.qos_submit_limit,
            submitted_since_start=submitted_total,
            failed_count=failed_total,
            throughput_caches_per_hour=round(throughput, 2),
            eta_hours=round(eta_hours, 2) if eta_hours is not None else None,
        )
        log(
            f"status cached={cache_count}/{len(runnable)} pending={len(pending)} "
            f"active_jobs={len(active)} running={running} queued={queued} "
            f"qos={active_qos_jobs}/{args.qos_submit_limit} throughput={throughput:.1f}/h",
            log_path,
        )
        if pending or active:
            time.sleep(args.poll_seconds if active or capacity == 0 else args.submit_retry_seconds)

    final_missing = [
        item for index, item in runnable.items() if index not in cached_indices
    ]
    if final_missing:
        append_failures(failed_path, final_missing)
    write_state(
        state_path,
        status="all_waves_complete" if not final_missing else "complete_with_failures",
        cached_count=len(cached_indices),
        runnable_count=len(runnable),
        skipped_count=len(skip_indices),
        final_missing=len(final_missing),
        failed_indices_path=str(failed_path),
    )
    log(f"all waves complete final_missing={len(final_missing)} skipped={len(skip_indices)}", log_path)
    return 0 if not final_missing else 3


def main() -> int:
    return run_controller(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
