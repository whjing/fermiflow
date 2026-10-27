#!/usr/bin/env python3
"""Create a modified Fermi XML model with a reproducible free-parameter policy.

The module uses only Python's standard library, so it can be run before either
Fermitools or Fermipy.  It never changes the input XML unless an explicit
output path equal to the input path is requested.
"""

from __future__ import annotations

import argparse
import ast
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NORMALIZATION_NAMES = {
    "prefactor",
    "norm",
    "normalization",
    "integral",
    "value",
    "amplitude",
}

FIXED_SPECTRAL_NAMES = {"eb", "scale", "pivotenergy", "pivot_energy", "energyscale"}


def angular_separation_deg(ra1, dec1, ra2, dec2):
    """Return great-circle separation in degrees."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cosine = (
        math.sin(dec1) * math.sin(dec2)
        + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def source_position(source):
    """Return (RA, DEC) for sources with a SkyDir-like spatial model."""
    spatial = source.find("spatialModel")
    if spatial is None:
        return None

    parameters = {
        item.get("name", "").upper(): item for item in spatial.findall("parameter")
    }
    try:
        return float(parameters["RA"].get("value")), float(parameters["DEC"].get("value"))
    except (KeyError, TypeError, ValueError):
        return None


def source_distance_deg(source, radial):
    """Return distance from the requested center, in degrees.

    Catalog XMLs created for an ROI normally carry ``ROI_Center_Distance``.
    That value is preferred when no alternative center was requested.
    """
    center = radial.get("center")
    if center is not None:
        position = source_position(source)
        if position is None:
            return None
        return angular_separation_deg(
            position[0], position[1], center["ra"], center["dec"]
        )

    try:
        return float(source.get("ROI_Center_Distance"))
    except (TypeError, ValueError):
        return None


def policy_from_radial(source, radial):
    """Resolve a radial-zone policy, or return ``None`` without a position."""
    if not radial:
        return None

    distance = source_distance_deg(source, radial)
    if distance is None:
        return None

    for zone in radial.get("zones", []):
        if distance <= float(zone["max_radius"]):
            return zone["policy"]
    return radial.get("outside_policy", "fixed")


def set_source_policy(source, policy):
    """Set one source's spectral freedom and return the number of changes.

    ``spectral`` means all fitted spectral parameters except the pivot/scale energy;
    spatial parameters remain fixed in every policy.
    """
    policy = policy.lower()
    if policy not in {"spectral", "norm", "fixed"}:
        raise ValueError(f"Unknown parameter policy: {policy}")

    changed = 0
    spectrum = source.find("spectrum")
    norm_parameter = None
    if spectrum is not None:
        for parameter in spectrum.findall("parameter"):
            if parameter.get("name", "").lower() in NORMALIZATION_NAMES:
                norm_parameter = parameter
                break
        if norm_parameter is None:
            parameters = spectrum.findall("parameter")
            norm_parameter = parameters[0] if parameters else None

    for parameter in source.iter("parameter"):
        new_value = "0"
        if parameter in (spectrum.findall("parameter") if spectrum is not None else []):
            name = parameter.get("name", "").lower()
            if policy == "spectral" and name not in FIXED_SPECTRAL_NAMES:
                new_value = "1"
            elif policy == "norm" and parameter is norm_parameter:
                new_value = "1"
        if parameter.get("free") != new_value:
            parameter.set("free", new_value)
            changed += 1
    return changed


def policy_for_source(source, config, ts_values):
    """Resolve one source's policy; explicit source rules take precedence."""
    name = source.get("name", "")
    explicit = config.get("sources", {})
    if name in explicit:
        return explicit[name]

    background_norms = set(config.get("background_norms", []))
    if name in background_norms:
        return "norm"

    radial = config.get("radial")
    ts_filter = config.get("ts_filter", {})
    if name in ts_values and ts_values[name] < float(ts_filter.get("threshold", 0)):
        ts_radial = ts_filter.get("radial")
        if ts_radial:
            # A low-TS rule normally uses the analysis centre already given by
            # the main radial policy.  It may still override that centre when
            # a different one is explicitly supplied under ts_filter.radial.
            ts_radial = dict(ts_radial)
            if "center" not in ts_radial and radial and radial.get("center"):
                ts_radial["center"] = radial["center"]
            policy = policy_from_radial(source, ts_radial)
            if policy is not None:
                return policy
        return ts_filter.get("policy", "fixed")

    policy = policy_from_radial(source, radial)
    if policy is not None:
        return policy

    return config.get("default_policy", "fixed")


def read_ts_values(results_file):
    """Read ``source name -> TS`` pairs from a gtlike ``*_results.dat`` file."""
    text = Path(results_file).read_text(encoding="utf-8", errors="replace")
    try:
        parsed = ast.literal_eval(text)
        return {
            name: float(values["TS value"])
            for name, values in parsed.items()
            if "TS value" in values
        }
    except (SyntaxError, ValueError, TypeError, AttributeError):
        pass

    source_pattern = re.compile(r"['\"](?P<name>[^'\"]+)['\"]\s*:\s*\{(?P<body>.*?)\}", re.DOTALL)
    ts_pattern = re.compile(r"['\"]TS value['\"]\s*:\s*['\"]?([-+0-9.eE]+)")
    values = {}
    for source_match in source_pattern.finditer(text):
        ts_match = ts_pattern.search(source_match.group("body"))
        if ts_match:
            values[source_match.group("name")] = float(ts_match.group(1))
    return values


def count_free_parameters(root):
    return sum(parameter.get("free") == "1" for parameter in root.iter("parameter"))


def apply_model_policy(input_model, output_model, config):
    """Apply a YAML-compatible policy dictionary and write a new XML model."""
    input_model = Path(input_model).expanduser().resolve()
    output_model = Path(output_model).expanduser().resolve()
    tree = ET.parse(input_model)
    root = tree.getroot()
    original_free_parameters = count_free_parameters(root)
    summary = []
    ts_filter = config.get("ts_filter", {})
    ts_values = (
        read_ts_values(ts_filter["results_file"])
        if ts_filter.get("results_file")
        else {}
    )

    for source in root.findall("source"):
        policy = policy_for_source(source, config, ts_values)
        changed = set_source_policy(source, policy)
        summary.append((source.get("name", ""), policy, changed))

    output_model.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output_model, encoding="UTF-8", xml_declaration=True)
    return summary, original_free_parameters, count_free_parameters(root)


def default_output_path(input_model):
    input_model = Path(input_model)
    return input_model.with_name(f"{input_model.stem}_edited{input_model.suffix}")


def load_model_policy(policy_file):
    """Read one standalone policy YAML; ``model_edit:`` is accepted for compatibility."""
    import yaml

    policy_file = Path(policy_file).expanduser().resolve()
    with policy_file.open(encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    policy = policy.get("model_edit", policy)
    ts_filter = policy.get("ts_filter", {})
    if ts_filter.get("results_file"):
        ts_filter = dict(ts_filter)
        results_file = Path(ts_filter["results_file"]).expanduser()
        ts_filter["results_file"] = str(
            results_file
            if results_file.is_absolute()
            else (policy_file.parent / results_file).resolve()
        )
        policy["ts_filter"] = ts_filter
    return policy


def direct_policy(args):
    """Build a policy from optional terminal arguments."""
    policy = {"default_policy": args.default_policy}
    if args.background_norm:
        policy["background_norms"] = args.background_norm
    if args.ts_results:
        policy["ts_filter"] = {
            "results_file": str(args.ts_results.expanduser().resolve()),
            "threshold": args.ts_threshold,
            "policy": args.ts_policy,
        }

    source_rules = {}
    for item in args.source_policy:
        try:
            name, source_policy = item.rsplit("=", 1)
        except ValueError as error:
            raise SystemExit("--source-policy must have the form NAME=spectral|norm|fixed") from error
        source_rules[name] = source_policy
    if source_rules:
        policy["sources"] = source_rules

    if args.free_spectral_within is not None or args.free_norm_until is not None:
        zones = []
        if args.free_spectral_within is not None:
            zones.append({"max_radius": args.free_spectral_within, "policy": "spectral"})
        if args.free_norm_until is not None:
            zones.append({"max_radius": args.free_norm_until, "policy": "norm"})
        policy["radial"] = {
            "zones": zones,
            "outside_policy": args.outside_policy,
        }
        if args.center_ra is not None or args.center_dec is not None:
            if args.center_ra is None or args.center_dec is None:
                raise SystemExit("Use both --center-ra and --center-dec, or neither.")
            policy["radial"]["center"] = {
                "ra": args.center_ra,
                "dec": args.center_dec,
            }
    return policy


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-model", type=Path, required=True)
    parser.add_argument("--policy", type=Path, help="Standalone YAML policy file.")
    parser.add_argument("--output-model", type=Path)
    parser.add_argument("--center-ra", type=float, help="Optional non-ROI radial center RA in degrees.")
    parser.add_argument("--center-dec", type=float, help="Optional non-ROI radial center Dec in degrees.")
    parser.add_argument(
        "--free-spectral-within", type=float,
        help="Free normalization and spectral-shape parameters inside this radius (deg).",
    )
    parser.add_argument("--free-norm-until", type=float, help="Free only normalization from the inner radius to this radius (deg).")
    parser.add_argument("--outside-policy", choices=("spectral", "norm", "fixed"), default="fixed")
    parser.add_argument("--default-policy", choices=("spectral", "norm", "fixed"), default="fixed")
    parser.add_argument("--source-policy", action="append", default=[], metavar="NAME=POLICY")
    parser.add_argument("--background-norm", action="append", default=[], metavar="NAME")
    parser.add_argument("--ts-results", type=Path, help="gtlike *_results.dat file containing per-source TS values.")
    parser.add_argument("--ts-threshold", type=float, default=1.0)
    parser.add_argument("--ts-policy", choices=("spectral", "norm", "fixed"), default="fixed")
    return parser.parse_args()


def main():
    args = parse_args()
    policy = load_model_policy(args.policy) if args.policy else direct_policy(args)
    output_model = args.output_model or default_output_path(args.input_model)
    _, original_free_parameters, free_parameters = apply_model_policy(
        args.input_model, output_model, policy
    )
    print(f"Input model : {args.input_model.expanduser().resolve()}")
    print(f"Output model: {output_model.expanduser().resolve()}")
    print(f"Free parameters: {original_free_parameters} -> {free_parameters}")


if __name__ == "__main__":
    main()
