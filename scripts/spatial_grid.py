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


MODEL_TYPES = {
    "point": ("PointSource", "SkyDirFunction"),
    "gaussian": ("RadialGaussian", "RadialGaussian"),
    "disk": ("RadialDisk", "RadialDisk"),
}
GAUSSIAN_R68_PER_SIGMA = math.sqrt(-2.0 * math.log(1.0 - 0.68))
DISK_R68_PER_RADIUS = math.sqrt(0.68)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Plot completed grid regions over plot.tsmap from the grid YAML.",
    )
    return parser.parse_args()


def resolve_path(value, base_dir):
    """Resolve one YAML path relative to its YAML file."""
    if value is None:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


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


def generate_grid(config_path):
    """Create XML, spatial YAML, Slurm scripts, and a manifest for every hypothesis."""
    base_dir = config_path.parent
    with config_path.open(encoding="utf-8") as handle:
        grid = yaml.safe_load(handle) or {}

    base = grid.get("base", {})
    input_model = resolve_path(base.get("input_model"), base_dir)
    template_path = resolve_path(base.get("spatial_template"), base_dir)
    output_root = resolve_path(base.get("output_root"), base_dir)
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

    slurm = dict(grid.get("slurm", {}))
    slurm["sbatch_dir"] = resolve_path(slurm.get("sbatch_dir", output_root / "sbatch"), base_dir)
    slurm["log_dir"] = resolve_path(slurm.get("log_dir", output_root / "logs"), base_dir)
    slurm["working_dir"] = resolve_path(slurm.get("working_dir", base_dir.parent / "scripts"), base_dir)
    slurm["conda_env"] = slurm.get("conda_env", "fermi")
    slurm["conda_sh"] = resolve_path(
        slurm.get("conda_sh", "/share/home/whjing/miniforge3/etc/profile.d/conda.sh"),
        base_dir,
    )
    slurm["sbatch_dir"].mkdir(parents=True, exist_ok=True)
    slurm["log_dir"].mkdir(parents=True, exist_ok=True)

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

        model_path = model_dir / f"{tag}_input.xml"
        ET.indent(tree, space="  ")
        tree.write(model_path, encoding="UTF-8", xml_declaration=True)

        spatial_config = copy.deepcopy(spatial_template)
        spatial_config.setdefault("fermipy", {}).setdefault("model", {})["catalogs"] = [str(model_path)]
        output_dir = output_root / tag
        spatial_config["output"] = str(output_dir)
        spatial_config["sources"] = grid_sources(source_configs, choices)
        spatial_config.setdefault("outputs", {})
        region_name = spatial_config["outputs"].setdefault("region_file", "spatial_fit_final.reg")
        spatial_config["outputs"].setdefault("model_name", "spatial_fit_final")

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
        "region_file",
        "sbatch_file",
        "model_policy",
        *(source["name"] for source in source_configs),
    ]
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    submit_script = slurm["sbatch_dir"] / "submit_spatial_grid.sh"
    write_submit_script(submit_script, sbatch_files)
    print(f"Generated {len(rows)} spatial hypotheses.")
    print(f"Manifest     : {manifest}")
    print(f"Submit script: {submit_script}")


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
    for index, row in enumerate(rows, start=1):
        axis = figure.add_subplot(nrows, ncols, index, projection=wcs)
        axis.imshow(
            data,
            origin="lower",
            cmap=plot_config.get("cmap", "inferno"),
            norm=PowerNorm(gamma=gamma, vmin=vmin, vmax=vmax),
        )
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
                text = region.meta.get("text", "")
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

    figure.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved spatial-grid plot: {output_png}")


def main():
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if args.plot:
        plot_grid(config_path)
    else:
        generate_grid(config_path)


if __name__ == "__main__":
    main()
