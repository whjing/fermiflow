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


def write_template(path: Path, template_name: str, replacements=None) -> None:
    """Copy one bundled generic YAML template without overwriting a file."""
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")

    template = script_directory() / "templates" / template_name
    if not template.is_file():
        raise SystemExit(f"Bundled template not found: {template_name}")
    text = template.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        text = text.replace(f"__{key.upper()}__", str(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Created template: {path}")


def spatial_replacements(target: str, energy_label: str):
    return {
        "target": target,
        "energy_label": energy_label,
        "analysis_name": f"{target}_{energy_label}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fermiflow",
        description="Run scripts from the currently installed fermiflow checkout.",
    )
    parser.add_argument("--version", action="version", version=f"fermiflow {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("path", help="Print the repository used by this command.")
    subparsers.add_parser("init", help="Copy the generic Fermitools project template.").add_argument(
        "config", nargs="?", type=Path, default=Path("project.yaml")
    )
    spatial_init = subparsers.add_parser(
        "init-spatial", help="Copy the generic Fermipy spatial-fit template."
    )
    spatial_init.add_argument("config", nargs="?", type=Path, default=Path("spatial.yaml"))
    spatial_init.add_argument("--target", default="my_target")
    spatial_init.add_argument("--energy-label", default="2GeV")
    spatial_grid_init = subparsers.add_parser(
        "init-spatial-grid", help="Copy the generic spatial-model grid template."
    )
    spatial_grid_init.add_argument(
        "config", nargs="?", type=Path, default=Path("spatial_grid.yaml")
    )
    spatial_grid_init.add_argument("--target", default="my_target")
    spatial_grid_init.add_argument("--energy-label", default="2GeV")
    subparsers.add_parser(
        "init-model-policy", help="Copy the generic XML free-parameter policy template."
    ).add_argument("config", nargs="?", type=Path, default=Path("model_policy.yaml"))
    subparsers.add_parser(
        "init-sed-filter", help="Copy the manually paired TS-filtered SED refit template."
    ).add_argument("config", nargs="?", type=Path, default=Path("sed_filter.yaml"))
    # Workflow-specific options are deliberately not duplicated here.  They
    # are collected below and passed straight to their implementing script.
    subparsers.add_parser("run", help="Run the Fermitools workflow.")
    subparsers.add_parser("spatial", help="Run the Fermipy spatial workflow.")
    subparsers.add_parser("spatial-grid", help="Generate or plot a grid of spatial hypotheses.")
    subparsers.add_parser("download", help="Download URLs in parallel with wget.")
    subparsers.add_parser("model", help="Create an XML with a parameter-freeing policy.")
    subparsers.add_parser("sed-filter", help="Make TS-filtered SED-bin XML models.")
    subparsers.add_parser("sed-submit", help="Write Slurm jobs for filtered SED-bin models.")

    # Forward unknown options to the selected workflow.  This lets users write
    # ``fermiflow spatial --config ...`` as well as the older ``-- --config``
    # form, without teaching this lightweight wrapper every workflow option.
    args, forwarded_args = parser.parse_known_args()
    if args.command in {"path", "init", "init-spatial", "init-spatial-grid", "init-model-policy", "init-sed-filter"} and forwarded_args:
        parser.error("unrecognized arguments: " + " ".join(forwarded_args))

    if args.command == "path":
        print(script_directory().parent)
        return

    if args.command == "init":
        write_template(args.config.expanduser().resolve(), "project.yaml")
        return

    if args.command == "init-spatial":
        write_template(
            args.config.expanduser().resolve(),
            "spatial.yaml",
            spatial_replacements(args.target, args.energy_label),
        )
        return

    if args.command == "init-spatial-grid":
        write_template(
            args.config.expanduser().resolve(),
            "spatial_grid.yaml",
            spatial_replacements(args.target, args.energy_label),
        )
        return

    if args.command == "init-model-policy":
        write_template(args.config.expanduser().resolve(), "model_policy.yaml")
        return

    if args.command == "init-sed-filter":
        write_template(args.config.expanduser().resolve(), "sed_filter.yaml")
        return

    script_name = {
        "run": "run_fermitools.py",
        "spatial": "run_spatial.py",
        "spatial-grid": "spatial_grid.py",
        "download": "download.sh",
        "model": "model_editor.py",
        "sed-filter": "sed_filter.py",
        "sed-submit": "sed_submit.py",
    }[args.command]
    raise SystemExit(run_script(script_name, forwarded_args))


if __name__ == "__main__":
    main()
