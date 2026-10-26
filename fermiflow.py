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

    sample = """# Copy this file once per target and edit the marked values.
analysis:
  target: my_target
  ra: 0.0                 # deg
  dec: 0.0                # deg
  roi_radius: 15.0        # deg
  emin: 100.0             # MeV
  emax: 500000.0          # MeV
  zmax: 90
  evclass: 128
  evtype: 3
  irfs: P8R3_SOURCE_V3
  mapsize_deg: 10.0
  binsz: 0.1

paths:
  # Shared across projects: catalog and diffuse backgrounds.
  common_data_dir: ~/data/fermi

  # Reusable inputs for this project only.
  project_data_dir: ../data
  rawdata_dir: ../rawdata
  products_dir: ../products_{energy_label}
  log_dir: ../logs

files:
  # Created here by prepare if it does not already exist.
  ltcube: "{project_data_dir}/{target}_ltcube.fits"
  catalog: gll_psc_16yr_v38.xml
  galactic: gll_iem_v07.fits
  isotropic: iso_P8R3_SOURCE_V3_v1.txt

  # Required only by --mode bin.
  # base_gti: "{products_dir}/{analysis_name}_gti.fits"
  # sed_model: "{project_data_dir}/models/my_target_sed_input.xml"
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample, encoding="utf-8")
    print(f"Created sample project configuration: {path}")


def write_sample_spatial_config(path: Path, target: str, energy_label: str) -> None:
    """Write a Fermipy spatial-fit template without overwriting an existing file."""
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")

    analysis_name = f"{target}_{energy_label}"
    sample = f"""# Paths below are resolved relative to this YAML file in configs/.
fermipy:
  logging:
    verbosity: 3

  data:
    evfile: ../products_{energy_label}/{analysis_name}_gti.fits
    scfile: ../rawdata/spacecraft.fits  # Change to the actual SC*.fits filename.
    ltcube: ../data/{target}_ltcube.fits

  binning:
    roiwidth: 10.0
    binsz: 0.05
    binsperdec: 8

  selection:
    ra: 0.0          # deg: replace with target center
    dec: 0.0         # deg: replace with target center
    emin: 1000.0     # MeV
    emax: 500000.0   # MeV
    zmax: 90
    evclass: 128
    evtype: 3
    tmin: 239557417  # MET: replace when needed
    tmax: 794361605  # MET: replace when needed
    filter: 'DATA_QUAL>0 && LAT_CONFIG==1'
    roicut: 'no'

  gtlike:
    edisp: false
    irfs: P8R3_SOURCE_V3
    edisp_disable: [isodiff, galdiff]

  model:
    galdiff: ~/data/fermi/gll_iem_v07.fits
    isodiff: ~/data/fermi/iso_P8R3_SOURCE_V3_v1.txt
    catalogs:
      - ../products_{energy_label}/{analysis_name}_input.xml

  optimizer:
    optimizer: MINUIT
    min_fit_quality: 2
    retries: 2
    tol: 1.0e-8

  # Defaults inherited by every extended source below.
  extension:
    make_tsmap: false
    make_plots: true
    fix_shape: true
    free_background: false
    width_min: 0.05
    width_max: 1.5
    width_nstep: 30
    fit_position: true

  # Defaults inherited by every localized point source below.
  localize:
    make_plots: false
    fix_shape: true
    dtheta_max: 1.0
    nstep: 20

output: ../products_{energy_label}/spatial_{target}
outputs:
  model_name: spatial_fit_final
  region_file: spatial_fit_final.reg

sources:
  # Names must exactly match the input XML.
  - name: {target}
    spatial_model: RadialGaussian
    extension: {{}}

  # Uncomment and edit only if the model contains these sources.
  # - name: extend
  #   spatial_model: RadialDisk
  #   extension:
  #     width_nstep: 30
  #     fit_position: true

  # - name: pt
  #   spatial_model: PointSource
  #   localization: {{}}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample, encoding="utf-8")
    print(f"Created sample spatial configuration: {path}")


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
    spatial_init = subparsers.add_parser(
        "init-spatial", help="Create a sample Fermipy spatial-fit YAML file."
    )
    spatial_init.add_argument("config", nargs="?", type=Path, default=Path("spatial.yaml"))
    spatial_init.add_argument("--target", default="my_target")
    spatial_init.add_argument("--energy-label", default="2GeV")
    subparsers.add_parser("run", help="Run the Fermitools workflow.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/run_kes27.py."
    )
    subparsers.add_parser("spatial", help="Run the Fermipy spatial workflow.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/run_spatial.py."
    )
    subparsers.add_parser("download", help="Download URLs in parallel with wget.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/download.sh."
    )
    subparsers.add_parser("model", help="Create an XML with a parameter-freeing policy.").add_argument(
        "args", nargs=argparse.REMAINDER, help="Arguments passed to scripts/model_editor.py."
    )

    args = parser.parse_args()
    if args.command == "path":
        print(script_directory().parent)
        return

    if args.command == "init":
        write_sample_config(args.config.expanduser().resolve())
        return

    if args.command == "init-spatial":
        write_sample_spatial_config(
            args.config.expanduser().resolve(), args.target, args.energy_label
        )
        return

    script_name = {
        "run": "run_kes27.py",
        "spatial": "run_spatial.py",
        "download": "download.sh",
        "model": "model_editor.py",
    }[args.command]
    raise SystemExit(run_script(script_name, args.args))


if __name__ == "__main__":
    main()
