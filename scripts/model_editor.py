#!/usr/bin/env python3
"""Create a modified Fermi XML model with a reproducible free-parameter policy.

The module uses only Python's standard library, so it can be run before either
Fermitools or Fermipy.  It never changes the input XML unless an explicit
output path equal to the input path is requested.
"""

from __future__ import annotations

import argparse
import math
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

    parameters = {item.get("name", "").upper(): item for item in spatial.findall("parameter")}
    try:
        return float(parameters["RA"].get("value")), float(parameters["DEC"].get("value"))
    except (KeyError, TypeError, ValueError):
        return None


def set_source_policy(source, policy):
    """Set one source to ``all``, ``norm``, or ``fixed`` and return changes."""
    policy = policy.lower()
    if policy not in {"all", "norm", "fixed"}:
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
        new_value = "1" if policy == "all" else "0"
        if policy == "norm" and parameter is norm_parameter:
            new_value = "1"
        if parameter.get("free") != new_value:
            parameter.set("free", new_value)
            changed += 1
    return changed


def policy_for_source(source, config):
    """Resolve one source's policy; explicit source rules take precedence."""
    name = source.get("name", "")
    explicit = config.get("sources", {})
    if name in explicit:
        return explicit[name]

    background_norms = set(config.get("background_norms", []))
    if name in background_norms:
        return "norm"

    radial = config.get("radial")
    if radial:
        distance = source_distance_deg(source, radial)
        if distance is not None:
            for zone in radial.get("zones", []):
                if distance <= float(zone["max_radius"]):
                    return zone["policy"]
            return radial.get("outside_policy", "fixed")

    return config.get("default_policy", "fixed")


def apply_model_policy(input_model, output_model, config):
    """Apply a YAML-compatible policy dictionary and write a new XML model."""
    input_model = Path(input_model).expanduser().resolve()
    output_model = Path(output_model).expanduser().resolve()
    tree = ET.parse(input_model)
    root = tree.getroot()
    summary = []

    for source in root.findall("source"):
        policy = policy_for_source(source, config)
        changed = set_source_policy(source, policy)
        summary.append((source.get("name", ""), policy, changed))

    output_model.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output_model, encoding="UTF-8", xml_declaration=True)
    return summary


def default_output_path(input_model):
    input_model = Path(input_model)
    return input_model.with_name(f"{input_model.stem}_edited{input_model.suffix}")


def load_model_policy(policy_file):
    """Read one standalone policy YAML; ``model_edit:`` is accepted for compatibility."""
    import yaml

    with Path(policy_file).expanduser().open(encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    return policy.get("model_edit", policy)


def direct_policy(args):
    """Build a policy from optional terminal arguments."""
    policy = {"default_policy": args.default_policy}
    if args.background_norm:
        policy["background_norms"] = args.background_norm

    source_rules = {}
    for item in args.source_policy:
        try:
            name, source_policy = item.rsplit("=", 1)
        except ValueError as error:
            raise SystemExit("--source-policy must have the form NAME=all|norm|fixed") from error
        source_rules[name] = source_policy
    if source_rules:
        policy["sources"] = source_rules

    if args.free_all_within is not None or args.free_norm_until is not None:
        zones = []
        if args.free_all_within is not None:
            zones.append({"max_radius": args.free_all_within, "policy": "all"})
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
    parser.add_argument("--free-all-within", type=float, help="Free all parameters inside this radius (deg).")
    parser.add_argument("--free-norm-until", type=float, help="Free only normalization from the inner radius to this radius (deg).")
    parser.add_argument("--outside-policy", choices=("all", "norm", "fixed"), default="fixed")
    parser.add_argument("--default-policy", choices=("all", "norm", "fixed"), default="fixed")
    parser.add_argument("--source-policy", action="append", default=[], metavar="NAME=POLICY")
    parser.add_argument("--background-norm", action="append", default=[], metavar="NAME")
    return parser.parse_args()


def main():
    args = parse_args()
    policy = load_model_policy(args.policy) if args.policy else direct_policy(args)
    output_model = args.output_model or default_output_path(args.input_model)
    summary = apply_model_policy(args.input_model, output_model, policy)
    print(f"Input model : {args.input_model.expanduser().resolve()}")
    print(f"Output model: {output_model.expanduser().resolve()}")
    for name, source_policy, changed in summary:
        print(f"{name:<35} {source_policy:<6} changed={changed}")


if __name__ == "__main__":
    main()
