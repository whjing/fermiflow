#!/usr/bin/env python3
"""Generate fixed XML models and independent Slurm jobs for TS maps."""
import argparse
import copy
import math
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

from spatial_grid import (
    conda_activation_lines, file_label, load_grid_config, resolve_path,
    resolve_slurm_config,
)


def write_job(path, tag, project, model, size, binsz, slurm):
    quote = lambda value: shlex.quote(str(value))
    lines = [
        "#!/usr/bin/env bash", f"#SBATCH --job-name={tag}",
        "#SBATCH --nodes=1", "#SBATCH --ntasks=1", "#SBATCH --cpus-per-task=1",
        f"#SBATCH --output={slurm['log_dir']}/%x-%j.log",
        f"#SBATCH --error={slurm['log_dir']}/%x-%j.log",
        "", "set -eo pipefail", *conda_activation_lines(slurm),
        "conda activate fermi", f"cd {quote(slurm['working_dir'])}",
        '# Isolate writable Fermitools parameters for this job.',
        'task_dir="$(mktemp -d "${TMPDIR:-/tmp}/fermiflow-tsmap.XXXXXX")"',
        'trap \'rm -rf -- "$task_dir"\' EXIT',
        'mkdir -p "$task_dir/pfiles"',
        'original_pfiles="${PFILES:?PFILES is missing after activating fermi}"',
        'export PFILES="$task_dir/pfiles;${original_pfiles#*;}"',
        'echo "Job: ${SLURM_JOB_ID:-unknown}; PFILES=$PFILES"',
        f"fermiflow run --config {quote(project)} --mode tsmap "
        f"--input-model {quote(model)} --size {size:g} --binsz {binsz:g} "
        f'--log-name "{tag}_${{SLURM_JOB_ID:-local}}"',
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o750)


def generate_grid(config_path, input_model):
    config_path = config_path.expanduser().resolve()
    base = config_path.parent
    config = load_grid_config(config_path)
    # CLI input is relative to the caller; YAML paths are relative to YAML.
    input_model = input_model.expanduser().resolve()
    project = resolve_path(config["project_config"], base)
    if not project.is_file():
        raise FileNotFoundError(project)
    tree = ET.parse(input_model)
    available = {source.get("name") for source in tree.getroot().findall("source")}
    output = resolve_path(config["output_dir"], base)
    tasks = config.get("tasks", [])
    defaults = config.get("defaults") or {}
    delay = float(config.get("submit_delay_seconds", 300))
    if not math.isfinite(delay) or delay < 0 or not tasks:
        raise ValueError("Provide tasks and a finite, nonnegative submit delay.")
    planned, tags = [], set()
    for task in tasks:
        removed = task.get("remove_sources", [])
        if not isinstance(removed, list) or any(not isinstance(name, str) for name in removed):
            raise ValueError("remove_sources must be a list of exact XML source names.")
        removed = list(dict.fromkeys(removed))
        missing = set(removed) - available
        if missing:
            raise ValueError(f"Sources not found in input XML: {', '.join(sorted(missing))}")
        tag = "tsmap-" + ("-".join(file_label(name) for name in removed) if removed else "res")
        if tag in tags:
            raise ValueError(f"Duplicate output tag: {tag}")
        tags.add(tag)
        size = float(task.get("size", defaults.get("size", 2)))
        binsz = float(task.get("binsz", defaults.get("binsz", .01)))
        if not all(math.isfinite(value) and value > 0 for value in (size, binsz)) or size < binsz:
            raise ValueError(f"Invalid size or binsz for {tag}")
        planned.append((tag, removed, size, binsz))
    slurm = resolve_slurm_config(config.get("slurm"), base, base.parent, "tsmap_grid")
    output.mkdir(parents=True, exist_ok=True)
    jobs = []
    for tag, removed, size, binsz in planned:
        model = output / f"{tag}.xml"
        if model == input_model:
            raise ValueError("Output XML would overwrite the input template; choose another output_dir.")
        root = copy.deepcopy(tree.getroot())
        for source in list(root.findall("source")):
            if source.get("name") in removed:
                root.remove(source)
        for parameter in root.iter("parameter"):
            parameter.set("free", "0")
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(model, encoding="UTF-8", xml_declaration=True)
        job = slurm["sbatch_dir"] / f"{tag}.sbatch"
        write_job(job, tag, project, model, size, binsz, slurm)
        jobs.append(job)
        print(f"{tag}: remove={removed}; size={size:g}; binsz={binsz:g}; map={model.with_suffix('.fits')}")
    submit = slurm["sbatch_dir"] / "submit_tsmap_grid.sh"
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "",
             "# Review the .sbatch files before running this script."]
    for index, job in enumerate(jobs):
        if index:
            lines.append(f"sleep {delay:g}")
        lines.append(f"sbatch {shlex.quote(str(job))}")
    submit.write_text("\n".join(lines) + "\n", encoding="utf-8")
    submit.chmod(0o750)
    print(f"Generated {len(jobs)} jobs; submit manually: bash {submit}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--input-model", required=True, type=Path)
    args = parser.parse_args()
    generate_grid(args.config, args.input_model)


if __name__ == "__main__":
    main()
