#!/usr/bin/env python
"""Submit Aurora climate-cache waves one at a time.

This controller is intentionally boring: keep one large Slurm array active,
wait for it to leave the queue, verify expected climate cache files, retry
missing indices, and then move to the next compact wave manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


WAVE_RE = re.compile(r"climate_wave_(?P<wave>\d+)_(?P<start>\d+)_(?P<end>\d+)\.csv$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous Aurora climate wave submitter.")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--wave-dir", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--model", default="aurora_subneptune_v1_dhuang")
    parser.add_argument("--slurm-script", default="roadrunner_egp/aurora_subneptune_grid/slurm/run_climate_cache.slurm")
    parser.add_argument("--start-wave", type=int, default=0)
    parser.add_argument("--end-wave", type=int, default=180)
    parser.add_argument("--throttle", type=int, default=999)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--post-wave-sleep-seconds", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-array-tasks", type=int, default=950)
    parser.add_argument("--stop-failure-fraction", type=float, default=0.50)
    parser.add_argument("--submit-retry-seconds", type=int, default=300)
    parser.add_argument("--adopt-first-job-id", default="")
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--failed-indices-path", required=True)
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


def read_wave_indices(path: Path) -> list[int]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [int(row["climate_group_index"]) for row in reader]


def cache_path(output_root: Path, climate_group_index: int) -> Path:
    return output_root / "climate_cache" / f"climate_{int(climate_group_index):02d}.npz"


def missing_indices(output_root: Path, indices: list[int]) -> list[int]:
    missing: list[int] = []
    for index in indices:
        path = cache_path(output_root, index)
        if not path.exists() or path.stat().st_size <= 0:
            missing.append(index)
    return missing


def compress_array(indices: list[int], throttle: int) -> str:
    if not indices:
        raise ValueError("Cannot build Slurm array spec for empty index list.")
    parts: list[str] = []
    start = prev = int(indices[0])
    for value in map(int, indices[1:]):
        if value == prev + 1:
            prev = value
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(parts) + f"%{int(throttle)}"


def write_state(path: Path, **state: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": now(), **state}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def submit_array(
    *,
    repo_root: Path,
    slurm_script: Path,
    model: str,
    manifest: Path,
    indices: list[int],
    throttle: int,
    wave: int,
    attempt: int,
    log_path: Path,
    retry_seconds: int,
) -> str:
    array_spec = compress_array(sorted(indices), throttle)
    env = os.environ.copy()
    env["MODEL"] = model
    env["MANIFEST"] = str(manifest)
    cmd = [
        "sbatch",
        "--parsable",
        f"--array={array_spec}",
        f"--job-name=aurora_clim_w{wave:03d}",
        "--export=ALL,MODEL,MANIFEST",
        str(slurm_script),
    ]
    while True:
        log(f"submitting wave={wave:03d} attempt={attempt} tasks={len(indices)} array={array_spec}", log_path)
        result = run(cmd, cwd=repo_root, env=env)
        if result.returncode == 0:
            job_id = result.stdout.strip().splitlines()[-1].strip()
            log(f"submitted wave={wave:03d} attempt={attempt} job_id={job_id}", log_path)
            return job_id
        log(
            "submit failed "
            f"wave={wave:03d} rc={result.returncode} stdout={result.stdout.strip()!r} "
            f"stderr={result.stderr.strip()!r}; retrying in {retry_seconds}s",
            log_path,
        )
        time.sleep(retry_seconds)


def wait_for_job(job_id: str, *, repo_root: Path, poll_seconds: int, log_path: Path) -> None:
    while True:
        result = run(["squeue", "-h", "-j", str(job_id)], cwd=repo_root)
        if result.returncode != 0:
            if "Invalid job id specified" in result.stderr:
                log(f"job left queue: {job_id}", log_path)
                return
            log(f"squeue failed for job={job_id}: {result.stderr.strip()!r}; retrying", log_path)
            time.sleep(poll_seconds)
            continue
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            log(f"job complete or left queue: {job_id}", log_path)
            return
        running = run(["squeue", "-h", "-j", str(job_id), "-t", "R"], cwd=repo_root)
        pending = run(["squeue", "-h", "-j", str(job_id), "-t", "PD"], cwd=repo_root)
        n_running = len([line for line in running.stdout.splitlines() if line.strip()])
        n_pending = len([line for line in pending.stdout.splitlines() if line.strip()])
        log(f"job active: {job_id} running={n_running} pending={n_pending}", log_path)
        time.sleep(poll_seconds)


def append_failures(path: Path, wave: int, indices: list[int]) -> None:
    if not indices:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for index in indices:
            handle.write(f"{wave:03d},{index}\n")


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    wave_dir = Path(args.wave_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    slurm_script = (repo_root / args.slurm_script).resolve()
    state_path = Path(args.state_path).expanduser().resolve()
    log_path = Path(args.log_path).expanduser().resolve()
    failed_indices_path = Path(args.failed_indices_path).expanduser().resolve()

    log(
        f"controller start waves={args.start_wave:03d}-{args.end_wave:03d} "
        f"throttle={args.throttle} adopt_first_job_id={args.adopt_first_job_id or 'none'}",
        log_path,
    )
    failed_indices_path.parent.mkdir(parents=True, exist_ok=True)
    failed_indices_path.write_text("", encoding="utf-8")

    for wave in range(args.start_wave, args.end_wave + 1):
        manifest, start, end = wave_file(wave_dir, wave)
        indices = read_wave_indices(manifest)
        expected_count = len(indices)
        write_state(
            state_path,
            status="wave_started",
            wave=wave,
            wave_start=start,
            wave_end=end,
            expected_count=expected_count,
            manifest=str(manifest),
        )
        log(f"wave={wave:03d} expected={expected_count} range={start}-{end}", log_path)

        if wave == args.start_wave and args.adopt_first_job_id:
            log(f"adopting existing wave={wave:03d} job_id={args.adopt_first_job_id}", log_path)
            wait_for_job(args.adopt_first_job_id, repo_root=repo_root, poll_seconds=args.poll_seconds, log_path=log_path)
            time.sleep(args.post_wave_sleep_seconds)

        missing = missing_indices(output_root, indices)
        attempt = 0
        while missing and attempt <= args.max_retries:
            attempt_missing = list(missing)
            chunks = [
                attempt_missing[offset : offset + args.max_array_tasks]
                for offset in range(0, len(attempt_missing), args.max_array_tasks)
            ]
            for chunk_index, chunk in enumerate(chunks):
                chunk = missing_indices(output_root, chunk)
                if not chunk:
                    continue
                job_id = submit_array(
                    repo_root=repo_root,
                    slurm_script=slurm_script,
                    model=args.model,
                    manifest=manifest,
                    indices=chunk,
                    throttle=args.throttle,
                    wave=wave,
                    attempt=attempt,
                    log_path=log_path,
                    retry_seconds=args.submit_retry_seconds,
                )
                write_state(
                    state_path,
                    status="wave_running",
                    wave=wave,
                    wave_start=start,
                    wave_end=end,
                    expected_count=expected_count,
                    missing_before_submit=len(missing),
                    submitted_count=len(chunk),
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                    job_id=job_id,
                    attempt=attempt,
                    manifest=str(manifest),
                )
                wait_for_job(job_id, repo_root=repo_root, poll_seconds=args.poll_seconds, log_path=log_path)
            time.sleep(args.post_wave_sleep_seconds)
            missing = missing_indices(output_root, indices)
            log(f"wave={wave:03d} attempt={attempt} missing_after={len(missing)}", log_path)
            attempt += 1

        if missing:
            append_failures(failed_indices_path, wave, missing)
            failure_fraction = len(missing) / max(1, expected_count)
            log(f"wave={wave:03d} unresolved_missing={len(missing)} fraction={failure_fraction:.3f}", log_path)
            if failure_fraction >= args.stop_failure_fraction:
                write_state(
                    state_path,
                    status="stopped_large_failure",
                    wave=wave,
                    unresolved_missing=len(missing),
                    failed_indices_path=str(failed_indices_path),
                )
                return 2

        complete_count = expected_count - len(missing)
        write_state(
            state_path,
            status="wave_complete",
            wave=wave,
            wave_start=start,
            wave_end=end,
            expected_count=expected_count,
            complete_count=complete_count,
            unresolved_missing=len(missing),
            failed_indices_path=str(failed_indices_path),
        )
        log(f"wave={wave:03d} complete={complete_count}/{expected_count}", log_path)

    final_missing: list[int] = []
    for wave in range(args.start_wave, args.end_wave + 1):
        manifest, _, _ = wave_file(wave_dir, wave)
        final_missing.extend(missing_indices(output_root, read_wave_indices(manifest)))
    append_failures(failed_indices_path, -1, final_missing)
    write_state(
        state_path,
        status="all_waves_complete",
        final_missing=len(final_missing),
        failed_indices_path=str(failed_indices_path),
    )
    log(f"all waves complete final_missing={len(final_missing)}", log_path)
    return 0 if not final_missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
