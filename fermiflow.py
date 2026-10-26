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


def write_sample_spatial_grid_config(path: Path, target: str, energy_label: str) -> None:
    """Write a non-destructive template for a spatial-model hypothesis grid."""
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")

    analysis_name = f"{target}_{energy_label}"
    sample = f"""# Generate XML, Fermipy YAML, and Slurm scripts for spatial hypotheses.
# Paths are resolved relative to this file in configs/.
base:
  input_model: ../products_{energy_label}/{analysis_name}_input.xml
  spatial_template: ../configs/spatial_{target}_{energy_label}.yaml
  output_root: ../products_{energy_label}/spatial_grid
  # model_policy: ../configs/modify-model.yaml

# Every present source contributes '<full-source-name>-<model>' to the tag.
# A source omitted by include: false is absent from the XML and the tag.
sources:
  - name: {target}
    include: [true]
    models: [point, gaussian, disk]
    # With no ra/dec here, template XML coordinates are retained.  r68 is
    # required only when an extended model cannot inherit a radial width.
    seed:
      r68: 0.33     # deg; converted automatically for Gaussian or Disk

  - name: extend
    include: [true]
    models: [gaussian, disk]
    seed: from_input_model

  - name: pt
    include: [true, false]
    models: [point]

# The generator only writes .sbatch files.  Run submit_spatial_grid.sh yourself.
slurm:
  conda_env: fermi
  conda_sh: /share/home/whjing/miniforge3/etc/profile.d/conda.sh
  working_dir: ../scripts
  nodes: [c001, c002, c003, c004, c005]
  sbatch_dir: ../sbatch/spatial_grid
  log_dir: ../logs/spatial_grid

# Run this stage only after inspecting the completed spatial regions.  It
# copies each <tag>_spatial_final.xml to <tag>_reloc_input.xml, reapplies the
# same free-parameter policy, then writes one gtlike job per completed model.
gtlike:
  project_config: ../configs/{target}_{energy_label}.yaml
  # model_policy: ../configs/modify-model.yaml
  slurm:
    sbatch_dir: ../sbatch/gtlike_grid
    log_dir: ../logs/gtlike_grid

comparison:
  output: ../products_{energy_label}/spatial_grid/likelihood_comparison.csv

# Optional visual check after jobs finish.  Leave this entire block commented
# if no common TS map is available; grid generation is unaffected.
# plot:
#   tsmap: ../products_{energy_label}/{analysis_name}_tsmap.fits
#   radio_contours: ../data/regions/{target}-radio.ctr
#   output: ../figures/{target}_spatial_grid.png
#   ncols: 4
#   cmap: inferno
#   power_gamma: 0.5
#   vmin: -1.0
#   vmax_percentile: 99.99
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample, encoding="utf-8")
    print(f"Created sample spatial-grid configuration: {path}")


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
    spatial_grid_init = subparsers.add_parser(
        "init-spatial-grid", help="Create a sample spatial-model grid YAML file."
    )
    spatial_grid_init.add_argument(
        "config", nargs="?", type=Path, default=Path("spatial_grid.yaml")
    )
    spatial_grid_init.add_argument("--target", default="my_target")
    spatial_grid_init.add_argument("--energy-label", default="2GeV")
    # Workflow-specific options are deliberately not duplicated here.  They
    # are collected below and passed straight to their implementing script.
    subparsers.add_parser("run", help="Run the Fermitools workflow.")
    subparsers.add_parser("spatial", help="Run the Fermipy spatial workflow.")
    subparsers.add_parser("spatial-grid", help="Generate or plot a grid of spatial hypotheses.")
    subparsers.add_parser("download", help="Download URLs in parallel with wget.")
    subparsers.add_parser("model", help="Create an XML with a parameter-freeing policy.")

    # Forward unknown options to the selected workflow.  This lets users write
    # ``fermiflow spatial --config ...`` as well as the older ``-- --config``
    # form, without teaching this lightweight wrapper every workflow option.
    args, forwarded_args = parser.parse_known_args()
    if args.command in {"path", "init", "init-spatial", "init-spatial-grid"} and forwarded_args:
        parser.error("unrecognized arguments: " + " ".join(forwarded_args))

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

    if args.command == "init-spatial-grid":
        write_sample_spatial_grid_config(
            args.config.expanduser().resolve(), args.target, args.energy_label
        )
        return

    script_name = {
        "run": "run_kes27.py",
        "spatial": "run_spatial.py",
        "spatial-grid": "spatial_grid.py",
        "download": "download.sh",
        "model": "model_editor.py",
    }[args.command]
    raise SystemExit(run_script(script_name, forwarded_args))


if __name__ == "__main__":
    main()
