"""Small command-line entry point for a checked-out fermiflow repository."""

from __future__ import annotations

import argparse
import json
from importlib import metadata, resources
import subprocess
import sys
from pathlib import Path

def version_text() -> str:
    """Report the installed package version and its source commit."""
    try:
        package = metadata.distribution("fermiflow")
    except metadata.PackageNotFoundError:
        return "fermiflow (not installed)"

    origin = json.loads(package.read_text("direct_url.json") or "{}")
    commit = origin.get("vcs_info", {}).get("commit_id")
    if not commit:
        commit_file = package.locate_file("scripts/_git_commit.txt")
        if commit_file.is_file():
            commit = commit_file.read_text(encoding="utf-8").strip()
    return f"fermiflow {package.version} (git: {commit or 'unknown'})"


INIT_TEMPLATES = {
    "project": "fermitools_project.yaml",
    "spatial": "spatial_fit.yaml",
    "spatial-grid": "spatial_grid.yaml",
    "tsmap-grid": "tsmap_grid.yaml",
    "spectral-grid": "spectral_grid.yaml",
    "model-policy": "model_policy.yaml",
    "sed-filter": "sed_filter.yaml",
}


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
        template = Path(__file__).resolve().parent / "templates" / template_name
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
    parser.add_argument("--version", action="version", version=version_text())

    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="Generate a YAML configuration template.")
    init.add_argument("--mode", required=True, choices=INIT_TEMPLATES)
    init.add_argument("--config", type=Path, help="Output YAML path (defaults to the template filename).")
    init.add_argument("--target", help="Target name for spatial templates (default: my_target).")
    init.add_argument("--energy-label", help="Energy label for spatial templates (default: 2GeV).")
    # Workflow-specific options are deliberately not duplicated here.  They
    # are collected below and passed straight to their implementing script.
    subparsers.add_parser("run", help="Run the Fermitools workflow.")
    subparsers.add_parser("spatial", help="Run the Fermipy spatial workflow.")
    subparsers.add_parser("spatial-grid", help="Generate or plot a grid of spatial hypotheses.")
    subparsers.add_parser("tsmap-grid", help="Generate TS-map XMLs and Slurm submission scripts.")
    subparsers.add_parser("spectral-grid", help="Generate and compare PL/LP spectral combinations.", add_help=False)
    subparsers.add_parser("download", help="Download URLs in parallel with wget.")
    subparsers.add_parser("model", help="Create an XML with a parameter-freeing policy.")
    subparsers.add_parser("sed-filter", help="Make TS-filtered SED-bin XML models.")
    subparsers.add_parser("sed-submit", help="Write Slurm jobs for filtered SED-bin models.")

    # Forward unknown options to the selected workflow.  This lets users write
    # ``fermiflow spatial --config ...`` as well as the older ``-- --config``
    # form, without teaching this lightweight wrapper every workflow option.
    args, forwarded_args = parser.parse_known_args()
    if args.command == "init":
        if forwarded_args:
            init.error("unrecognized arguments: " + " ".join(forwarded_args))

        template = INIT_TEMPLATES[args.mode]
        replacements = None
        if args.mode in {"spatial", "spatial-grid", "tsmap-grid"}:
            replacements = spatial_replacements(
                args.target or "my_target", args.energy_label or "2GeV"
            )
        elif args.target is not None or args.energy_label is not None:
            init.error("--target and --energy-label are only available for spatial and tsmap-grid templates")

        output = args.config or Path(template)
        write_template(output.expanduser().resolve(), template, replacements)
        return

    script_name = {
        "run": "run_fermitools.py",
        "spatial": "fit_spatial.py",
        "spatial-grid": "spatial_grid.py",
        "tsmap-grid": "tsmap_grid.py",
        "spectral-grid": "spectral_grid.py",
        "download": "download.sh",
        "model": "edit_model.py",
        "sed-filter": "sed_filter.py",
        "sed-submit": "sed_submit.py",
    }[args.command]
    raise SystemExit(run_script(script_name, forwarded_args))


if __name__ == "__main__":
    main()
