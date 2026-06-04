#!/usr/bin/env python
"""Download and verify PICASO 4 reference data in the isolated picaso4 folder."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFDATA = REPO_ROOT / "picaso4_reference"
OLD_REFDATA = Path("/Users/xin/Documents/Documents/College/timestep/picaso/reference")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch PICASO 4 reference data without touching the old PICASO 3.4 data."
    )
    parser.add_argument(
        "--refdata",
        type=Path,
        default=DEFAULT_REFDATA,
        help=f"Target PICASO 4 reference folder. Default: {DEFAULT_REFDATA}",
    )
    parser.add_argument(
        "--skip-resampled-opacity",
        action="store_true",
        help="Skip the required default resampled opacity download.",
    )
    parser.add_argument(
        "--skip-stellar-grids",
        action="store_true",
        help="Skip optional stellar-grid downloads.",
    )
    parser.add_argument(
        "--skip-phoenix",
        action="store_true",
        help="Skip the optional Phoenix stellar grid download.",
    )
    parser.add_argument(
        "--skip-virga",
        action="store_true",
        help="Skip the optional default Virga Mieff data download.",
    )
    parser.add_argument(
        "--skip-virga-aggregates",
        action="store_true",
        help="Skip the optional Virga aggregate Mieff data download.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only run picaso.data.check_environ() using the target paths.",
    )
    return parser.parse_args()


def bootstrap_reference_from_github(refdata: Path) -> None:
    """Fetch the GitHub reference folder when picaso.data cannot bootstrap it."""
    if (refdata / "config.json").exists():
        return
    if shutil.which("git") is None:
        raise RuntimeError("git is required to bootstrap the PICASO reference folder.")

    with tempfile.TemporaryDirectory(prefix="picaso4_reference_") as tmp:
        clone_dir = Path(tmp) / "picaso"
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "https://github.com/natashabatalha/picaso.git",
                str(clone_dir),
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "sparse-checkout", "set", "reference"],
            check=True,
        )
        github_reference = clone_dir / "reference"
        if not (github_reference / "config.json").exists():
            raise RuntimeError(f"GitHub reference folder did not contain config.json: {github_reference}")
        shutil.copytree(github_reference, refdata, dirs_exist_ok=True)


def has_non_readme_content(path: Path) -> bool:
    if not path.exists():
        return False
    ignored = {"readme", ".ds_store", "__macosx"}
    return any(child.name.lower() not in ignored for child in path.iterdir())


def cleanup_archives(path: Path, names: tuple[str, ...]) -> None:
    for name in names:
        archive = path / name
        if archive.exists():
            archive.unlink()
            print(f"Removed downloaded archive after extraction: {archive}")


def cleanup_download_metadata(path: Path) -> None:
    for ds_store in path.rglob(".DS_Store"):
        ds_store.unlink()
    for metadata_dir in path.rglob("__MACOSX"):
        shutil.rmtree(metadata_dir)
    for empty_dir in sorted(path.rglob("*"), reverse=True):
        if empty_dir.is_dir():
            try:
                empty_dir.rmdir()
            except OSError:
                pass


def ensure_stellar_grid(picaso_data, pysyn_cdbs: Path, grid_name: str) -> None:
    """Download or repair a stellar grid in PYSYN_CDBS/grid."""
    target = pysyn_cdbs / "grid" / grid_name
    nested = pysyn_cdbs / "grid" / "grp" / "redcat" / "trds" / "grid" / grid_name

    if target.exists():
        print(f"{grid_name} stellar grid already exists: {target}")
        return

    if nested.exists():
        print(f"Moving extracted {grid_name} stellar grid into place: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(nested), str(target))
        return

    print(f"Downloading {grid_name} stellar grid into PYSYN_CDBS.")
    picaso_data.get_data(
        category_download="stellar_grids",
        target_download=grid_name,
    )

    if nested.exists() and not target.exists():
        print(f"Moving extracted {grid_name} stellar grid into place: {target}")
        shutil.move(str(nested), str(target))

    cleanup_archives(pysyn_cdbs / "grid", ("synphot3.tar.gz", "synphot5.tar.gz"))
    cleanup_download_metadata(pysyn_cdbs / "grid")

    if not target.exists():
        raise RuntimeError(f"Expected stellar grid was not installed: {target}")


def ensure_virga_mieff(picaso_data, refdata: Path, target_download: str, folder_name: str, archive_name: str) -> None:
    """Download Virga Mieff data into its expected reference-data folder."""
    destination = refdata / folder_name
    destination.mkdir(parents=True, exist_ok=True)

    if has_non_readme_content(destination):
        print(f"Virga {target_download} data already exists: {destination}")
        cleanup_archives(destination, (archive_name,))
        return

    print(f"Downloading Virga {target_download} Mieff data into {destination}.")
    picaso_data.get_data(
        category_download="virga_mieff",
        target_download=target_download,
        final_destination_dir=destination,
    )
    cleanup_archives(destination, (archive_name,))
    cleanup_download_metadata(destination)

    if not has_non_readme_content(destination):
        raise RuntimeError(f"Expected Virga data was not installed: {destination}")


def main() -> int:
    args = parse_args()
    refdata = args.refdata.expanduser().resolve()
    pysyn_cdbs = refdata / "stellar_grids"

    if refdata == OLD_REFDATA.resolve():
        raise SystemExit(f"Refusing to use old frozen reference data folder: {refdata}")

    refdata.mkdir(parents=True, exist_ok=True)
    pysyn_cdbs.mkdir(parents=True, exist_ok=True)

    os.environ["picaso_refdata"] = str(refdata)
    os.environ["PYSYN_CDBS"] = str(pysyn_cdbs)

    import picaso.data as picaso_data

    print("PICASO 4 reference-data target")
    print(f"  picaso_refdata={os.environ['picaso_refdata']}")
    print(f"  PYSYN_CDBS={os.environ['PYSYN_CDBS']}")

    if not args.check_only:
        print("Downloading/updating required PICASO reference folder...")
        if (refdata / "config.json").exists():
            print("Reference config.json already exists; leaving reference folder in place.")
        else:
            try:
                picaso_data.get_reference(os.environ["picaso_refdata"])
            except FileNotFoundError as exc:
                print(f"PICASO get_reference bootstrap failed: {exc}")
                print("Bootstrapping the reference folder from GitHub sparse checkout instead.")
                bootstrap_reference_from_github(refdata)

        if args.skip_resampled_opacity:
            print("Skipping resampled opacity download by request.")
        else:
            opacity_db = refdata / "opacities" / "opacities_0.3_15_R15000.db"
            if opacity_db.exists():
                print(f"Default resampled opacity database already exists: {opacity_db}")
            else:
                print("Downloading default resampled opacity data. PICASO docs note this is about 7 GB.")
                _input_config, data_config = picaso_data.get_data_config()
                picaso_data.get_data(
                    category_download="resampled_opacity",
                    target_download="default",
                    final_destination_dir=data_config["resampled_opacity"]["default"]["default_destination"],
                )

        if args.skip_stellar_grids:
            print("Skipping stellar-grid downloads by request.")
        else:
            ensure_stellar_grid(picaso_data, pysyn_cdbs, "ck04models")
            if args.skip_phoenix:
                print("Skipping Phoenix stellar-grid download by request.")
            else:
                ensure_stellar_grid(picaso_data, pysyn_cdbs, "phoenix")

        if args.skip_virga:
            print("Skipping default Virga Mieff download by request.")
        else:
            ensure_virga_mieff(picaso_data, refdata, "default", "virga", "virga.zip")

        if args.skip_virga_aggregates:
            print("Skipping Virga aggregate Mieff download by request.")
        else:
            ensure_virga_mieff(
                picaso_data,
                refdata,
                "aggregates",
                "virga_aggregates",
                "VIRGA_2_mieff_files.zip",
            )

    print("Running PICASO environment check...")
    picaso_data.check_environ()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
