#!/usr/bin/env python3
"""Generate and inspect a grid of Fermipy spatial-model hypotheses.

The generator creates one XML model, one spatial YAML, and one Slurm script
per hypothesis.  It does not submit jobs.  Use ``--plot`` after jobs finish
to compare the generated DS9 regions on one optional TS map.
"""

from __future__ import annotations

import argparse
import copy
import csv
import itertools
import math
import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from model_editor import apply_model_policy, load_model_policy


MODEL_TYPES = {
    "point": ("PointSource", "SkyDirFunction"),
    "gaussian": ("RadialGaussian", "RadialGaussian"),
    "disk": ("RadialDisk", "RadialDisk"),
}
GAUSSIAN_R68_PER_SIGMA = math.sqrt(-2.0 * math.log(1.0 - 0.68))
DISK_R68_PER_RADIUS = math.sqrt(0.68)
NLL_RE = re.compile(r"-log\(Likelihood\):\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)")
GTLIKE_DONE_TEXT = "[DONE] gtlike (MINUIT) finished"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--plot",
        action="store_true",
        help="Plot completed grid regions over plot.tsmap from the grid YAML.",
    )
    action.add_argument(
        "--prepare-gtlike",
        action="store_true",
        help="Create relocated XML models and Slurm gtlike jobs from completed spatial fits.",
    )
    action.add_argument(
        "--compare-likelihood",
        action="store_true",
        help="Rank completed gtlike jobs using manifest-recorded stable logs.",
    )
    return parser.parse_args()


def resolve_path(value, base_dir):
    """Resolve one YAML path relative to its YAML file."""
    if value is None:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def load_grid_config(config_path):
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def output_root_from_grid(grid, base_dir):
    output_root = resolve_path(grid.get("base", {}).get("output_root"), base_dir)
    if output_root is None:
        raise ValueError("base.output_root is required in spatial_grid.yaml.")
    return output_root


def read_manifest(path):
    if not path.is_file():
        raise FileNotFoundError(f"Grid manifest not found: {path}")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_manifest(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def extend_fieldnames(rows, required_fields):
    existing = list(rows[0]) if rows else []
    return [*existing, *(field for field in required_fields if field not in existing)]


def file_label(value):
    """Keep full source names while making them safe as path components."""
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
    return label.strip("-") or "source"


def model_key(value):
    key = str(value).lower()
    if key not in MODEL_TYPES:
        valid = ", ".join(MODEL_TYPES)
        raise ValueError(f"Unknown spatial model '{value}'; use one of: {valid}.")
    return key


def source_options(source_config):
    """Return every present/absent and model option for one configured source."""
    include_values = source_config.get("include", [True])
    options = []
    for include in include_values:
        if not include:
            options.append({"include": False, "model": None})
            continue
        for model in source_config.get("models", []):
            options.append({"include": True, "model": model_key(model)})
    if not options:
        raise ValueError(f"Source '{source_config.get('name')}' has no grid options.")
    return options


def source_spatial(source):
    spatial = source.find("spatialModel")
    if spatial is None:
        raise ValueError(f"Source '{source.get('name')}' has no spatialModel.")
    parameters = {item.get("name"): item for item in spatial.findall("parameter")}
    try:
        ra = float(parameters["RA"].get("value"))
        dec = float(parameters["DEC"].get("value"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Source '{source.get('name')}' has no usable RA/DEC parameters."
        ) from error
    return spatial, parameters, ra, dec


def source_r68(spatial, parameters):
    """Derive containment r68 from an existing radial model, in degrees."""
    try:
        if spatial.get("type") == "RadialGaussian":
            return float(parameters["Sigma"].get("value")) * GAUSSIAN_R68_PER_SIGMA
        if spatial.get("type") == "RadialDisk":
            return float(parameters["Radius"].get("value")) * DISK_R68_PER_RADIUS
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Source has an invalid {spatial.get('type')} width parameter."
        ) from error
    return None


def build_spatial_model(model, ra, dec, r68=None):
    """Build a fixed-position Fermitools spatial model from common r68 input."""
    source_type, spatial_type = MODEL_TYPES[model]
    spatial = ET.Element("spatialModel", type=spatial_type)

    if model == "gaussian":
        if r68 is None:
            raise ValueError("An r68 seed is required for a Gaussian model.")
        ET.SubElement(
            spatial,
            "parameter",
            free="0",
            name="Sigma",
            max="10",
            min="0",
            scale="1",
            value=f"{r68 / GAUSSIAN_R68_PER_SIGMA:.8f}",
        )
    elif model == "disk":
        if r68 is None:
            raise ValueError("An r68 seed is required for a Disk model.")
        ET.SubElement(
            spatial,
            "parameter",
            free="0",
            name="Radius",
            max="10",
            min="0",
            scale="1",
            value=f"{r68 / DISK_R68_PER_RADIUS:.8f}",
        )

    ET.SubElement(
        spatial,
        "parameter",
        free="0",
        name="RA",
        max="360",
        min="-360",
        scale="1",
        value=f"{ra:.8f}",
    )
    ET.SubElement(
        spatial,
        "parameter",
        free="0",
        name="DEC",
        max="90",
        min="-90",
        scale="1",
        value=f"{dec:.8f}",
    )
    return source_type, spatial


def set_source_spatial_model(source, model, seed=None):
    """Replace one source's spatial model, retaining template coordinates by default."""
    old_spatial, parameters, template_ra, template_dec = source_spatial(source)
    if seed == "from_input_model":
        seed = {}
    if seed is not None and not isinstance(seed, dict):
        raise ValueError(
            f"Seed for source '{source.get('name')}' must be a mapping or 'from_input_model'."
        )
    seed = seed or {}
    ra = float(seed.get("ra", template_ra))
    dec = float(seed.get("dec", template_dec))
    r68 = seed.get("r68")
    if r68 is None and model != "point":
        r68 = source_r68(old_spatial, parameters)
    if r68 is not None:
        r68 = float(r68)
        if r68 <= 0:
            raise ValueError(f"Source '{source.get('name')}' has non-positive seed r68.")

    source_type, spatial = build_spatial_model(model, ra, dec, r68)
    source.remove(old_spatial)
    source.append(spatial)
    source.set("type", source_type)


def hypothesis_tag(source_configs, choices):
    """Use full source names and short model names; omit absent sources entirely."""
    parts = []
    for source_config, choice in zip(source_configs, choices):
        if choice["include"]:
            parts.append(f"{file_label(source_config['name'])}-{choice['model']}")
    return "-".join(parts)


def resolve_template_paths(config, base_dir):
    """Make copied Fermipy YAML paths independent of the generated YAML location."""
    config = copy.deepcopy(config)
    for key in ("evfile", "scfile", "ltcube"):
        if key in config.get("fermipy", {}).get("data", {}):
            config["fermipy"]["data"][key] = str(
                resolve_path(config["fermipy"]["data"][key], base_dir)
            )
    for key in ("galdiff", "isodiff"):
        if key in config.get("fermipy", {}).get("model", {}):
            config["fermipy"]["model"][key] = str(
                resolve_path(config["fermipy"]["model"][key], base_dir)
            )
    return config


def grid_sources(source_configs, choices):
    sources = []
    for source_config, choice in zip(source_configs, choices):
        if not choice["include"]:
            continue
        model_name, _ = MODEL_TYPES[choice["model"]]
        source = {"name": source_config["name"], "spatial_model": model_name}
        source["localization" if choice["model"] == "point" else "extension"] = {}
        sources.append(source)
    return sources


def write_sbatch(path, tag, config_path, slurm, model_policy):
    """Write one independent Slurm job; submission remains an explicit later step."""
    nodes = slurm.get("nodes", [])
    node = nodes[slurm["index"] % len(nodes)] if nodes else None
    directives = [
        f"#SBATCH --job-name={tag}",
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --cpus-per-task=1",
    ]
    if node:
        directives.append(f"#SBATCH --nodelist={node}")
    directives.extend(
        [
            f"#SBATCH --output={slurm['log_dir']}/%x-%j.log",
            f"#SBATCH --error={slurm['log_dir']}/%x-%j.log",
        ]
    )
    policy_argument = ""
    if model_policy:
        policy_argument = f" --model-policy {shlex.quote(str(model_policy))}"

    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                *directives,
                "",
                "set -eo pipefail",
                f"source {shlex.quote(str(slurm['conda_sh']))}",
                f"conda activate {shlex.quote(str(slurm['conda_env']))}",
                f"cd {shlex.quote(str(slurm['working_dir']))}",
                f"exec fermiflow spatial --config {shlex.quote(str(config_path))}{policy_argument}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o750)


def write_submit_script(path, sbatch_files):
    """Write a manual submit helper that submits the already generated jobs."""
    commands = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review the .sbatch files before running this script.",
    ]
    commands.extend(f"sbatch {shlex.quote(str(item))}" for item in sbatch_files)
    commands.append("")
    path.write_text("\n".join(commands), encoding="utf-8")
    path.chmod(0o750)


def build_relocated_input(template_model, spatial_model, output_model, row, source_names):
    """Copy one fixed template, changing only grid-source spatial information.

    The Fermipy XML supplies the fitted spatial model and parameters.  Every
    spectrum, diffuse component, unrelated source, and original free state
    comes from ``template_model``.  Sources marked absent in the grid row are
    removed from the copied template.
    """
    template_tree = ET.parse(template_model)
    template_root = template_tree.getroot()
    fitted_root = ET.parse(spatial_model).getroot()
    template_sources = {
        source.get("name"): source for source in template_root.findall("source")
    }
    fitted_sources = {
        source.get("name"): source for source in fitted_root.findall("source")
    }

    for source_name in source_names:
        template_source = template_sources.get(source_name)
        if template_source is None:
            raise ValueError(f"Source missing from gtlike template XML: {source_name}")

        if row.get(source_name) == "absent":
            template_root.remove(template_source)
            continue

        fitted_source = fitted_sources.get(source_name)
        fitted_spatial = (
            fitted_source.find("spatialModel") if fitted_source is not None else None
        )
        if fitted_spatial is None:
            raise ValueError(
                f"Source '{source_name}' has no fitted spatial model in {spatial_model}"
            )

        old_spatial = template_source.find("spatialModel")
        if old_spatial is not None:
            template_source.remove(old_spatial)
        new_spatial = copy.deepcopy(fitted_spatial)
        for parameter in new_spatial.findall("parameter"):
            parameter.set("free", "0")
        template_source.append(new_spatial)
        template_source.set("type", fitted_source.get("type", template_source.get("type")))

    output_model.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(template_tree, space="  ")
    template_tree.write(output_model, encoding="UTF-8", xml_declaration=True)


def resolve_slurm_config(config, base_dir, default_root, default_name):
    """Resolve one Slurm block and create its stable output directories."""
    config = dict(config or {})
    config["sbatch_dir"] = resolve_path(
        config.get("sbatch_dir", default_root / "sbatch" / default_name), base_dir
    )
    config["log_dir"] = resolve_path(
        config.get("log_dir", default_root / "logs" / default_name), base_dir
    )
    config["working_dir"] = resolve_path(
        config.get("working_dir", base_dir.parent / "scripts"), base_dir
    )
    config["conda_env"] = config.get("conda_env", "fermi")
    config["conda_sh"] = resolve_path(
        config.get("conda_sh", "/share/home/whjing/miniforge3/etc/profile.d/conda.sh"),
        base_dir,
    )
    config["sbatch_dir"].mkdir(parents=True, exist_ok=True)
    config["log_dir"].mkdir(parents=True, exist_ok=True)
    return config


def write_gtlike_sbatch(path, tag, project_config, input_model, job_log, slurm):
    """Write one gtlike job that records a deterministic log beside its XML."""
    nodes = slurm.get("nodes", [])
    node = nodes[slurm["index"] % len(nodes)] if nodes else None
    directives = [
        f"#SBATCH --job-name=like-{tag}",
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --cpus-per-task=1",
    ]
    if node:
        directives.append(f"#SBATCH --nodelist={node}")
    directives.extend(
        [
            f"#SBATCH --output={slurm['log_dir']}/%x-%j.log",
            f"#SBATCH --error={slurm['log_dir']}/%x-%j.log",
        ]
    )
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                *directives,
                "",
                "set -eo pipefail",
                f"source {shlex.quote(str(slurm['conda_sh']))}",
                f"conda activate {shlex.quote(str(slurm['conda_env']))}",
                f"cd {shlex.quote(str(slurm['working_dir']))}",
                f"mkdir -p {shlex.quote(str(job_log.parent))}",
                "# tee preserves a stable per-model log; pipefail preserves failures.",
                f"fermiflow run --config {shlex.quote(str(project_config))} --mode like "
                f"--input-model {shlex.quote(str(input_model))} 2>&1 | "
                f"tee {shlex.quote(str(job_log))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o750)


def generate_grid(config_path):
    """Create XML, spatial YAML, Slurm scripts, and a manifest for every hypothesis."""
    base_dir = config_path.parent
    grid = load_grid_config(config_path)

    base = grid.get("base", {})
    input_model = resolve_path(base.get("input_model"), base_dir)
    template_path = resolve_path(base.get("spatial_template"), base_dir)
    output_root = output_root_from_grid(grid, base_dir)
    model_policy = resolve_path(base.get("model_policy"), base_dir)
    if not input_model or not input_model.is_file():
        raise FileNotFoundError(f"Input XML not found: {input_model}")
    if not template_path or not template_path.is_file():
        raise FileNotFoundError(f"Spatial YAML template not found: {template_path}")
    if model_policy and not model_policy.is_file():
        raise FileNotFoundError(f"Model policy not found: {model_policy}")

    source_configs = grid.get("sources", [])
    if not source_configs:
        raise ValueError("No sources are configured in spatial_grid.yaml.")
    for source in source_configs:
        if not source.get("name"):
            raise ValueError("Every grid source needs an exact XML 'name'.")

    with template_path.open(encoding="utf-8") as handle:
        spatial_template = resolve_template_paths(yaml.safe_load(handle) or {}, template_path.parent)

    original_tree = ET.parse(input_model)
    source_names = {item.get("name") for item in original_tree.getroot().findall("source")}
    configured_names = {item["name"] for item in source_configs}
    missing_names = configured_names - source_names
    if missing_names:
        raise ValueError(f"Sources missing from input XML: {sorted(missing_names)}")

    output_root.mkdir(parents=True, exist_ok=True)
    model_dir = output_root / "models"
    config_dir = output_root / "configs"
    model_dir.mkdir(exist_ok=True)
    config_dir.mkdir(exist_ok=True)

    slurm = resolve_slurm_config(grid.get("slurm"), base_dir, output_root, "spatial_grid")

    rows = []
    sbatch_files = []
    options = [source_options(item) for item in source_configs]
    for index, choices in enumerate(itertools.product(*options)):
        tag = hypothesis_tag(source_configs, choices)
        tree = copy.deepcopy(original_tree)
        root = tree.getroot()
        xml_sources = {item.get("name"): item for item in root.findall("source")}

        for source_config, choice in zip(source_configs, choices):
            source = xml_sources[source_config["name"]]
            if not choice["include"]:
                root.remove(source)
                continue
            set_source_spatial_model(source, choice["model"], source_config.get("seed"))

        # This XML belongs to the Fermipy spatial stage.  Reserve *_input.xml
        # for the later Fermitools/gtlike stage.
        model_path = model_dir / f"{tag}_spatial.xml"
        ET.indent(tree, space="  ")
        tree.write(model_path, encoding="UTF-8", xml_declaration=True)

        spatial_config = copy.deepcopy(spatial_template)
        spatial_config.setdefault("fermipy", {}).setdefault("model", {})["catalogs"] = [str(model_path)]
        output_dir = output_root / tag
        spatial_config["output"] = str(output_dir)
        spatial_config["sources"] = grid_sources(source_configs, choices)
        spatial_config.setdefault("outputs", {})
        # A tag-specific region filename makes copied/collected regions
        # unambiguous even outside their individual output directories.
        region_name = f"{tag}.reg"
        spatial_config["outputs"]["region_file"] = region_name
        # The final XML is also tag-specific so it remains identifiable after
        # copying it outside this hypothesis directory.
        spatial_config["outputs"]["model_name"] = f"{tag}_spatial_final"

        config_file = config_dir / f"spatial_{tag}.yaml"
        with config_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(spatial_config, handle, allow_unicode=True, sort_keys=False)

        slurm["index"] = index
        sbatch_file = slurm["sbatch_dir"] / f"{tag}.sbatch"
        write_sbatch(sbatch_file, tag, config_file, slurm, model_policy)
        sbatch_files.append(sbatch_file)

        row = {
            "tag": tag,
            "input_model": str(model_path),
            "spatial_config": str(config_file),
            "output_dir": str(output_dir),
            "spatial_final_model": str(
                output_dir / f"{spatial_config['outputs']['model_name']}.xml"
            ),
            "region_file": str(output_dir / region_name),
            "sbatch_file": str(sbatch_file),
            "model_policy": "" if model_policy is None else str(model_policy),
        }
        row.update(
            {
                source_config["name"]: choice["model"] if choice["include"] else "absent"
                for source_config, choice in zip(source_configs, choices)
            }
        )
        rows.append(row)

    manifest = output_root / "spatial_grid_manifest.csv"
    fieldnames = [
        "tag",
        "input_model",
        "spatial_config",
        "output_dir",
        "spatial_final_model",
        "region_file",
        "sbatch_file",
        "model_policy",
        *(source["name"] for source in source_configs),
    ]
    write_manifest(manifest, rows, fieldnames)

    submit_script = slurm["sbatch_dir"] / "submit_spatial_grid.sh"
    write_submit_script(submit_script, sbatch_files)
    print(f"Generated {len(rows)} spatial hypotheses.")
    print(f"Manifest     : {manifest}")
    print(f"Submit script: {submit_script}")


def prepare_gtlike(config_path):
    """Turn completed Fermipy spatial models into fixed-space gtlike inputs."""
    base_dir = config_path.parent
    grid = load_grid_config(config_path)
    output_root = output_root_from_grid(grid, base_dir)
    manifest = output_root / "spatial_grid_manifest.csv"
    rows = read_manifest(manifest)
    like_config = grid.get("gtlike")
    if not like_config:
        raise SystemExit("No gtlike block is set in spatial_grid.yaml.")

    project_config = resolve_path(like_config.get("project_config"), base_dir)
    if project_config is None or not project_config.is_file():
        raise FileNotFoundError(f"gtlike.project_config not found: {project_config}")
    template_model = resolve_path(
        like_config.get("template_model", grid.get("base", {}).get("input_model")),
        base_dir,
    )
    if template_model is None or not template_model.is_file():
        raise FileNotFoundError(f"gtlike.template_model not found: {template_model}")
    policy_value = like_config.get("model_policy", grid.get("base", {}).get("model_policy"))
    model_policy = resolve_path(policy_value, base_dir)
    if model_policy and not model_policy.is_file():
        raise FileNotFoundError(f"gtlike model policy not found: {model_policy}")
    policy = load_model_policy(model_policy) if model_policy else None

    slurm_values = dict(grid.get("slurm") or {})
    slurm_values.update(like_config.get("slurm") or {})
    slurm = resolve_slurm_config(slurm_values, base_dir, output_root, "gtlike_grid")
    sbatch_files = []
    prepared = 0

    for index, row in enumerate(rows):
        expected_final_model = Path(
            row.get("spatial_final_model")
            or Path(row["output_dir"]) / f"{row['tag']}_spatial_final.xml"
        )
        final_model = expected_final_model
        if not final_model.is_file():
            # Support grid runs made before final XML names were normalized:
            # Fermipy wrote names such as <tag>_spatial_final_00.xml.
            candidates = sorted(
                expected_final_model.parent.glob(f"{expected_final_model.stem}_*.xml"),
                key=lambda path: path.stat().st_mtime,
            )
            if candidates:
                final_model = candidates[-1]
        if not final_model.is_file():
            row["gtlike_status"] = "spatial_pending"
            continue

        output_dir = Path(row["output_dir"])
        reloc_input = output_dir / f"{row['tag']}_reloc_input.xml"
        build_relocated_input(
            template_model,
            final_model,
            reloc_input,
            row,
            source_names=[item["name"] for item in grid.get("sources", [])],
        )
        if policy:
            _, original_free, final_free = apply_model_policy(
                reloc_input, reloc_input, policy
            )
            print(f"Prepared {row['tag']}: free parameters {original_free} -> {final_free}")
        else:
            print(f"Prepared {row['tag']}: copied template spectrum/background with fitted spatial parameters")

        job_log = output_dir / "gtlike.log"
        slurm["index"] = index
        sbatch_file = slurm["sbatch_dir"] / f"{row['tag']}_gtlike.sbatch"
        write_gtlike_sbatch(
            sbatch_file,
            row["tag"],
            project_config,
            reloc_input,
            job_log,
            slurm,
        )
        row.update(
            {
                "spatial_final_model": str(final_model),
                "reloc_input_model": str(reloc_input),
                "gtlike_log": str(job_log),
                "gtlike_sbatch": str(sbatch_file),
                "gtlike_status": "prepared",
            }
        )
        sbatch_files.append(sbatch_file)
        prepared += 1

    fields = extend_fieldnames(
        rows,
        ["reloc_input_model", "gtlike_log", "gtlike_sbatch", "gtlike_status"],
    )
    write_manifest(manifest, rows, fields)
    submit_script = slurm["sbatch_dir"] / "submit_gtlike_grid.sh"
    write_submit_script(submit_script, sbatch_files)
    print(f"Prepared {prepared} gtlike jobs from completed spatial fits.")
    print(f"Updated manifest: {manifest}")
    print(f"Submit script   : {submit_script}")


def read_gtlike_result(row):
    """Read only the final MINUIT likelihood from the stable manifest log."""
    log_path = Path(row.get("gtlike_log", ""))
    if not log_path.is_file():
        return {"status": "log_missing", "complete": False, "nll": None}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    values = [float(value) for value in NLL_RE.findall(text)]
    complete = GTLIKE_DONE_TEXT in text
    if not values:
        return {"status": "likelihood_missing", "complete": complete, "nll": None}
    return {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "nll": values[-1],
    }


def print_source_comparisons(rows, source_names):
    """Compare one source while holding every configured companion fixed."""
    for source_name in source_names:
        groups = {}
        for row in rows:
            companions = tuple(
                (name, row.get(name, "")) for name in source_names if name != source_name
            )
            groups.setdefault(companions, []).append(row)

        printed = False
        for companions, group in sorted(groups.items()):
            variants = {item.get(source_name, "") for item in group}
            if len(variants) < 2:
                continue
            if not printed:
                print(f"\n{source_name} comparisons")
                print("-" * (len(source_name) + 12))
                printed = True
            best = min(group, key=lambda item: item["nll"])
            details = "; ".join(
                f"{item.get(source_name)}: ΔTS={2 * (item['nll'] - best['nll']):.2f}"
                for item in sorted(group, key=lambda item: item["nll"])
            )
            companions_text = ", ".join(f"{name}={value}" for name, value in companions)
            print(f"{companions_text}: best={best.get(source_name)}; {details}")


def print_optional_source_tests(rows, source_names):
    """Print TS for optional-source presence tests whenever an absent pair exists."""
    for source_name in source_names:
        groups = {}
        for row in rows:
            companions = tuple(
                (name, row.get(name, "")) for name in source_names if name != source_name
            )
            groups.setdefault(companions, []).append(row)

        for companions, group in sorted(groups.items()):
            absent = next((item for item in group if item.get(source_name) == "absent"), None)
            if absent is None:
                continue
            for present in (item for item in group if item.get(source_name) != "absent"):
                ts = 2.0 * (absent["nll"] - present["nll"])
                companions_text = ", ".join(f"{name}={value}" for name, value in companions)
                print(
                    f"TS_{file_label(source_name)} ({present.get(source_name)}; "
                    f"{companions_text}) = {ts:.2f}"
                )


def compare_likelihood(config_path):
    """Rank completed gtlike combinations using manifest metadata, not filename rules."""
    base_dir = config_path.parent
    grid = load_grid_config(config_path)
    output_root = output_root_from_grid(grid, base_dir)
    manifest = output_root / "spatial_grid_manifest.csv"
    rows = read_manifest(manifest)
    source_names = [item["name"] for item in grid.get("sources", [])]

    completed = []
    for row in rows:
        row.update(read_gtlike_result(row))
        if row["complete"] and row["nll"] is not None:
            completed.append(row)

    print(f"Configured combinations : {len(rows)}")
    print(f"Completed gtlike models : {len(completed)}")
    if not completed:
        print("No completed gtlike logs are available yet.")
        return

    best = min(row["nll"] for row in completed)
    ordered = sorted(completed, key=lambda item: item["nll"])
    print("\nAll completed models")
    print("--------------------")
    print(f"{'rank':>4}  {'model':<58}  {'-logL':>15}  {'ΔTS from best':>14}")
    for rank, row in enumerate(ordered, start=1):
        row["rank"] = rank
        row["delta_ts_from_best"] = 2.0 * (row["nll"] - best)
        print(
            f"{rank:4d}  {row['tag']:<58}  {row['nll']:15.2f}  "
            f"{row['delta_ts_from_best']:14.2f}"
        )

    print_source_comparisons(ordered, source_names)
    print("\nOptional-source contribution tests")
    print("----------------------------------")
    print_optional_source_tests(ordered, source_names)

    comparison = grid.get("comparison", {})
    output = resolve_path(
        comparison.get("output", output_root / "likelihood_comparison.csv"), base_dir
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "tag",
        "nll",
        "delta_ts_from_best",
        "complete",
        "status",
        "gtlike_log",
        *source_names,
    ]
    write_manifest(output, ordered, fields)
    print(f"\nSaved likelihood comparison: {output}")


def read_ds9_contours(contour_file):
    """Read DS9 .ctr contour blocks as (RA, Dec) lists."""
    contours = []
    current = None
    with contour_file.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line == "(":
                current = []
            elif line == ")":
                if current:
                    contours.append(current)
                current = None
            elif current is not None:
                fields = line.split()
                if len(fields) >= 2:
                    try:
                        current.append((float(fields[0]), float(fields[1])))
                    except ValueError:
                        pass
    return contours


def region_label(region):
    """Keep only the source name in plot labels, not DS9 fit annotations."""
    text = str(region.meta.get("text", "")).strip()
    return re.split(r"\s+(?:pos_)?r68=", text, maxsplit=1)[0]


def plot_grid(config_path):
    """Plot completed DS9 regions over the optional TS map declared in YAML."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.io import fits
        from astropy.wcs import WCS
        from matplotlib.colors import PowerNorm
        from regions import CircleSkyRegion, Regions
    except ImportError as error:
        raise SystemExit(
            "Plotting needs matplotlib, astropy, and regions in the active environment."
        ) from error

    base_dir = config_path.parent
    with config_path.open(encoding="utf-8") as handle:
        grid = yaml.safe_load(handle) or {}
    plot_config = grid.get("plot")
    if not plot_config or not plot_config.get("tsmap"):
        raise SystemExit("No plot.tsmap is set in spatial_grid.yaml; nothing to plot.")

    output_root = resolve_path(grid.get("base", {}).get("output_root"), base_dir)
    manifest = output_root / "spatial_grid_manifest.csv"
    if not manifest.is_file():
        raise FileNotFoundError(f"Grid manifest not found: {manifest}")
    with manifest.open(encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if Path(row["region_file"]).is_file()]
    if not rows:
        raise SystemExit("No completed region files are listed in the grid manifest.")

    tsmap_file = resolve_path(plot_config["tsmap"], base_dir)
    output_png = resolve_path(
        plot_config.get("output", output_root / "spatial_grid.png"), base_dir
    )
    radio_file = resolve_path(plot_config.get("radio_contours"), base_dir)
    ncols = int(plot_config.get("ncols", 4))
    gamma = float(plot_config.get("power_gamma", 0.5))
    vmin = float(plot_config.get("vmin", -1.0))
    percentile = float(plot_config.get("vmax_percentile", 99.99))

    with fits.open(tsmap_file) as hdul:
        data = hdul[0].data.squeeze()
        header = hdul[0].header
    while data.ndim > 2:
        data = data[0]
    wcs = WCS(header).celestial
    contours = read_ds9_contours(radio_file) if radio_file and radio_file.is_file() else []

    nrows = math.ceil(len(rows) / ncols)
    figure = plt.figure(figsize=(4.5 * ncols, 3.8 * nrows))
    vmax = np.nanpercentile(data, percentile)
    axes = []
    image = None
    for index, row in enumerate(rows, start=1):
        axis = figure.add_subplot(nrows, ncols, index, projection=wcs)
        image = axis.imshow(
            data,
            origin="lower",
            cmap=plot_config.get("cmap", "inferno"),
            norm=PowerNorm(gamma=gamma, vmin=vmin, vmax=vmax),
        )
        axes.append(axis)
        for contour in contours:
            if len(contour) >= 2:
                ra, dec = zip(*contour)
                axis.plot(
                    ra,
                    dec,
                    transform=axis.get_transform("world"),
                    color="lime",
                    linewidth=0.8,
                )
        for region in Regions.read(row["region_file"], format="ds9"):
            axis.add_artist(region.to_pixel(wcs).as_artist(linewidth=1.5))
            if isinstance(region, CircleSkyRegion):
                text = region_label(region)
                if text:
                    axis.text(
                        region.center.ra.deg,
                        region.center.dec.deg,
                        text,
                        transform=axis.get_transform("world"),
                        color="cyan",
                        fontsize=7,
                    )
        axis.set_title(row["tag"], fontsize=8)
        axis.coords[0].set_axislabel("RA")
        axis.coords[1].set_axislabel("Dec")
        axis.coords[0].set_ticklabel(size=7)
        axis.coords[1].set_ticklabel(size=7)

    figure.tight_layout(rect=(0.0, 0.0, 0.92, 1.0))
    colorbar = figure.colorbar(image, ax=axes, shrink=0.84, pad=0.02)
    colorbar.set_label(plot_config.get("colorbar_label", "TS"))
    output_png.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved spatial-grid plot: {output_png}")


def main():
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if args.plot:
        plot_grid(config_path)
    elif args.prepare_gtlike:
        prepare_gtlike(config_path)
    elif args.compare_likelihood:
        compare_likelihood(config_path)
    else:
        generate_grid(config_path)


if __name__ == "__main__":
    main()
