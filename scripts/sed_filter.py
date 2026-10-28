#!/usr/bin/env python3
"""Create TS-filtered SED-bin models from manually paired XML/results files.

Every XML/results pair is deliberately listed by hand in a YAML file.  This
prevents a result from one energy bin ever being applied accidentally to an
XML model from another bin.
"""

from __future__ import annotations

import argparse
import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


NORMALIZATION_NAMES = {
    "prefactor", "norm", "normalization", "integral", "value", "amplitude"
}


def resolve_path(value, base_dir):
    """Resolve one YAML path relative to the YAML file itself."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def read_ts_values(results_file):
    """Read source-name/TS pairs from a gtlike ``*_results.dat`` file."""
    text = results_file.read_text(encoding="utf-8", errors="replace")
    try:
        values = ast.literal_eval(text)
        return {
            name: float(source["TS value"])
            for name, source in values.items()
            if "TS value" in source
        }
    except (SyntaxError, ValueError, TypeError, AttributeError):
        pass

    sources = re.compile(r"['\"](?P<name>[^'\"]+)['\"]\s*:\s*\{(?P<body>.*?)\}", re.DOTALL)
    ts_pattern = re.compile(r"['\"]TS value['\"]\s*:\s*['\"]?([-+0-9.eE]+)")
    return {
        match.group("name"): float(ts.group(1))
        for match in sources.finditer(text)
        if (ts := ts_pattern.search(match.group("body")))
    }


def count_free_parameters(root):
    return sum(parameter.get("free") == "1" for parameter in root.iter("parameter"))


def normalization_parameter(source):
    """Return the source spectrum's normalization parameter, if any."""
    spectrum = source.find("spectrum")
    if spectrum is None:
        return None
    parameters = spectrum.findall("parameter")
    for parameter in parameters:
        if parameter.get("name", "").lower() in NORMALIZATION_NAMES:
            return parameter
    return parameters[0] if parameters else None


def fix_low_ts_source(source, keep_normalization):
    """Fix all source parameters, optionally preserving norm's free state."""
    norm = normalization_parameter(source) if keep_normalization else None
    changed = 0
    for parameter in source.iter("parameter"):
        if parameter is norm:
            continue
        if parameter.get("free") != "0":
            parameter.set("free", "0")
            changed += 1
    return changed


def indent_xml(element, level=0):
    """Indent XML without relying on ``ET.indent`` (Python 3.8 compatible)."""
    prefix = "\n" + "  " * level
    child_prefix = "\n" + "  " * (level + 1)
    children = list(element)
    if children:
        if not element.text or not element.text.strip():
            element.text = child_prefix
        for child in children:
            indent_xml(child, level + 1)
        if not children[-1].tail or not children[-1].tail.strip():
            children[-1].tail = prefix
    if level and (not element.tail or not element.tail.strip()):
        element.tail = prefix


def output_model_path(input_model, threshold):
    """Return a downstream-compatible ``*-tsltX_input.xml`` name."""
    suffix = f"-tslt{threshold:g}_input.xml"
    if input_model.name.endswith("_input.xml"):
        return input_model.with_name(input_model.name.removesuffix("_input.xml") + suffix)
    return input_model.with_name(input_model.stem + suffix)


def filter_one_job(job, threshold, keep_normalization_sources):
    """Make one filtered XML from one explicitly supplied XML/results pair."""
    input_model = job["input_model"]
    results_file = job["results_file"]
    output_model = job.get("output_model") or output_model_path(input_model, threshold)

    if not input_model.is_file():
        raise FileNotFoundError(f"Input XML not found: {input_model}")
    if not results_file.is_file():
        raise FileNotFoundError(f"Results file not found: {results_file}")

    ts_values = read_ts_values(results_file)
    if not ts_values:
        raise ValueError(f"No source TS values found in: {results_file}")

    tree = ET.parse(input_model)
    root = tree.getroot()
    original_free = count_free_parameters(root)
    fixed_sources = []
    untouched_sources = []

    for source in root.findall("source"):
        name = source.get("name", "")
        ts = ts_values.get(name)
        if ts is None or ts >= threshold:
            untouched_sources.append((name, ts))
            continue

        keep_norm = name in keep_normalization_sources
        changed = fix_low_ts_source(source, keep_norm)
        fixed_sources.append((name, ts, changed, keep_norm))

    output_model.parent.mkdir(parents=True, exist_ok=True)
    indent_xml(root)
    tree.write(output_model, encoding="UTF-8", xml_declaration=True)
    return {
        "ibin": job["ibin"],
        "input_model": input_model,
        "results_file": results_file,
        "output_model": output_model,
        "original_free": original_free,
        "final_free": count_free_parameters(root),
        "fixed_sources": fixed_sources,
        "untouched_sources": untouched_sources,
    }


def load_config(config_file):
    config_file = Path(config_file).expanduser().resolve()
    with config_file.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config = config.get("sed_filter", config)
    base_dir = config_file.parent

    required = ("project_config", "nbins", "jobs")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError("Missing sed-filter setting(s): " + ", ".join(missing))

    if not config["jobs"]:
        raise ValueError("jobs must contain at least one manually paired XML/results entry.")

    jobs = []
    for item in config["jobs"]:
        if not {"ibin", "input_model", "results_file"} <= set(item):
            raise ValueError("Each jobs entry needs ibin, input_model, and results_file.")
        job = dict(item)
        job["ibin"] = int(job["ibin"])
        job["input_model"] = resolve_path(job["input_model"], base_dir)
        job["results_file"] = resolve_path(job["results_file"], base_dir)
        if job.get("output_model"):
            job["output_model"] = resolve_path(job["output_model"], base_dir)
        jobs.append(job)

    ibins = [job["ibin"] for job in jobs]
    if len(ibins) != len(set(ibins)):
        raise ValueError("Each SED bin may appear only once in jobs.")
    if any(ibin < 1 or ibin > int(config["nbins"]) for ibin in ibins):
        raise ValueError("Every ibin must be between 1 and nbins.")

    slurm = config.get("slurm", {})
    return {
        "config_file": config_file,
        "project_config": resolve_path(config["project_config"], base_dir),
        "nbins": int(config["nbins"]),
        "threshold": float(config.get("ts_threshold", 2.0)),
        "keep_normalization_sources": set(config.get("keep_normalization_sources", [])),
        "jobs": sorted(jobs, key=lambda job: job["ibin"]),
        "working_dir": resolve_path(config.get("working_dir", "."), base_dir),
        "sbatch_dir": resolve_path(slurm.get("sbatch_dir", "../sbatch/sed_filter"), base_dir),
        "log_dir": resolve_path(slurm.get("log_dir", "../logs/sed_filter"), base_dir),
        "conda_env": slurm.get("conda_env", "fermi"),
        "conda_sh": resolve_path(
            slurm.get("conda_sh", "~/miniforge3/etc/profile.d/conda.sh"), base_dir
        ),
        "nodes": list(slurm.get("nodes", ["c001", "c002", "c003", "c004", "c005"])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = load_config(args.config)

    if not settings["project_config"].is_file():
        raise FileNotFoundError(f"Project configuration not found: {settings['project_config']}")
    for job in settings["jobs"]:
        result = filter_one_job(
            job, settings["threshold"], settings["keep_normalization_sources"]
        )
        print("\n" + "=" * 78)
        print(f"SED bin      : {result['ibin']}/{settings['nbins']}")
        print(f"Input model  : {result['input_model']}")
        print(f"Results file : {result['results_file']}")
        print(f"Output model : {result['output_model']}")
        print(f"Free parameters: {result['original_free']} -> {result['final_free']}")
        print(f"Sources fixed (TS < {settings['threshold']:g}): {len(result['fixed_sources'])}")
        for name, ts, changed, kept_norm in result["fixed_sources"]:
            suffix = "; normalization kept" if kept_norm else ""
            print(f"  {name:<35} TS={ts:10.4f}  fixed={changed}{suffix}")

if __name__ == "__main__":
    main()
