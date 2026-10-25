"""Small command-line entry point for a checked-out fermiflow repository."""

from __future__ import annotations

import argparse
from importlib import resources
import subprocess
import sys
from pathlib import Path

__version__ = "0.1.0"


def script_directory() -> Path:
    """Return the installed directory containing bundled workflow scripts."""
    return Path(str(resources.files("scripts")))


def run_script(script_name: str, script_args: list[str]) -> int:
    script = script_directory() / script_name
    if not script.is_file():
        raise SystemExit(
            f"Cannot find {script}. Reinstall or repair this checkout."
        )

    if script_args[:1] == ["--"]:
        script_args = script_args[1:]

    command = ["bash", str(script)] if script.suffix == ".sh" else [sys.executable, str(script)]
    return subprocess.run([*command, *script_args], check=False).returncode


def write_sample_config(path: Path) -> None:
    """Write a minimal project YAML without overwriting an existing file."""
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")

    sample = """# Copy this file once per target and edit the marked values.\nanalysis:\n  target: my_target\n  ra: 0.0                 # deg\n  dec: 0.0                # deg\n  roi_radius: 15.0        # deg\n  emin: 100.0             # MeV\n  emax: 500000.0          # MeV\n  zmax: 90\n  evclass: 128\n  evtype: 3\n  irfs: P8R3_SOURCE_V3\n  mapsize_deg: 10.0\n  binsz: 0.1\n\npaths:\n  template_dir: ../data_template\n  rawdata_dir: ../rawdata\n  products_dir: ../products_{energy_label}\n  log_dir: ../logs\n\nfiles:\n  # Set this to null to create a fresh livetime cube during prepare.\n  ltcube: ../data_template/my_target_ltcube.fits\n  catalog: gll_psc_16yr_v38.xml\n  galactic: gll_iem_v07.fits\n  isotropic: iso_P8R3_SOURCE_V3_v1.txt\n\n  # Required only by --mode bin.\n  # base_gti: \"{products_dir}/{analysis_name}_gti.fits\"\n  # sed_model: \"{products_dir}/my_target_sed_input.xml\"\n"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample, encoding="utf-8")
    print(f"Created sample project configuration: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fermiflow",
        description="Run scripts from the currently installed fermiflow checkout.",
    )
    parser.add_argument("--version", action="version", version=f"fermiflow {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("path", help="Print the repository used by this command.")
    subparsers.add_parser("init", help="Create a sample Fermitools YAML file.").add_argument(
        "config", nargs="?", type=Path, default=Path("project.yaml")
    )
    subparsers.add_parser("run", help="Run the Fermitools workflow.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/run_kes27.py."
    )
    subparsers.add_parser("spatial", help="Run the Fermipy spatial workflow.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/run_spatial.py."
    )
    subparsers.add_parser("download", help="Download URLs in parallel with wget.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/download.sh."
    )

    args = parser.parse_args()
    if args.command == "path":
        print(script_directory().parent)
        return

    if args.command == "init":
        write_sample_config(args.config.expanduser().resolve())
        return

    script_name = {
        "run": "run_kes27.py",
        "spatial": "run_spatial.py",
        "download": "download.sh",
    }[args.command]
    raise SystemExit(run_script(script_name, args.args))


if __name__ == "__main__":
    main()
