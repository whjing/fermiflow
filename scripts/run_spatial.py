#!/usr/bin/env python3
"""Run one Fermipy spatial-fit configuration.

Example:
    python spatial_fit.py --config ../configs/spatial_2gev.yaml
"""

import argparse
import copy
import logging
import math
from pathlib import Path

import yaml
from fermipy.gtanalysis import GTAnalysis
from model_editor import apply_model_policy, default_output_path, load_model_policy
from utils import configure_logger, require_file, render_path


logger = logging.getLogger("spatial_fit")


GAUSSIAN_R68_PER_SIGMA = math.sqrt(-2.0 * math.log(1.0 - 0.68))
DISK_R68_PER_RADIUS = math.sqrt(0.68)


def extended_r68(spatial_model, spatial_width):
    """Convert a Fermipy spatial-template width in degrees to containment r68."""
    if spatial_width is None or spatial_width <= 0:
        return None
    if spatial_model == "RadialGaussian":
        return spatial_width * GAUSSIAN_R68_PER_SIGMA
    if spatial_model == "RadialDisk":
        return spatial_width * DISK_R68_PER_RADIUS
    return None


def localization_r68(localization_result):
    """Return Fermipy's 68% localization radius in degrees, when available."""
    if not localization_result:
        return None

    value = localization_result.get("pos_r68", localization_result.get("r68"))
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def write_ds9_regions(gta, source_configs, region_file, localization_results=None):
    """Write fitted centers, extended-source r68, and point localization r68."""
    localization_results = localization_results or {}

    with region_file.open("w", encoding="utf-8") as handle:
        handle.write("# Region file format: DS9 version 4.1\n")
        handle.write(
            'global color=cyan width=2 font="helvetica 10 normal roman" '
            "select=1 highlite=1 dash=0 fixed=0 edit=1 move=1 "
            "delete=1 include=1 source=1\n"
        )
        handle.write("fk5\n")

        for source_config in source_configs:
            source_name = source_config["name"]

            if source_name not in gta.roi:
                logger.warning(
                    "Source not found while writing region, skipped: %s",
                    source_name,
                )
                continue

            source = gta.roi.get_source_by_name(source_name)
            ra = source["ra"]
            dec = source["dec"]
            spatial_model = source["SpatialModel"]
            requested_model = source_config.get("spatial_model", "PointSource")
            is_point_source = requested_model == "PointSource"

            if is_point_source:
                pos_r68 = localization_r68(localization_results.get(source_name))
                if pos_r68 is not None:
                    handle.write(
                        f"circle({ra:.6f},{dec:.6f},{pos_r68:.6f}d) "
                        f"# color=yellow dash=1 text={{{source_name} pos_r68={pos_r68:.4f} deg}}\n"
                    )
                else:
                    logger.warning(
                        "No pos_r68 available for point source %s; writing center only.",
                        source_name,
                    )
            else:
                r68 = extended_r68(spatial_model, source.get("SpatialWidth"))
                if r68 is None:
                    logger.warning(
                        "Cannot derive r68 for %s with spatial model %s; writing center only.",
                        source_name,
                        spatial_model,
                    )
                else:
                    handle.write(
                        f"circle({ra:.6f},{dec:.6f},{r68:.6f}d) "
                        f"# color=cyan text={{{source_name} r68={r68:.4f} deg}}\n"
                    )

            handle.write(
                f"point({ra:.6f},{dec:.6f}) "
                f"# point=cross color=cyan text={{{source_name}}}\n"
            )

    logger.info("DS9 region written: %s", region_file)


def write_final_products(
    gta,
    source_configs,
    outdir,
    output_config,
    localization_results=None,
):
    """Write the final Fermipy XML model and matching DS9 region file."""

    model_name = Path(
        output_config.get("model_name", "spatial_fit_final")
    ).stem
    region_name = output_config.get(
        "region_file",
        f"{model_name}.reg",
    )

    gta.write_roi(model_name, make_plots=False)

    model_file = outdir / f"{model_name}.xml"
    region_file = outdir / region_name

    write_ds9_regions(gta, source_configs, region_file, localization_results)

    logger.info("Final ROI model: %s", model_file)
    logger.info("Final DS9 region: %s", region_file)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--model-policy", type=Path,
        help="Optional standalone YAML policy used to create edited catalog XML files.",
    )
    return parser.parse_args()


def resolve_path(value, base_dir):
    """Resolve one path relative to the YAML file directory."""
    if value is None or not isinstance(value, str):
        return value

    path = Path(value).expanduser()
    return str(path if path.is_absolute() else (base_dir / path).resolve())


def resolve_fermipy_paths(config, base_dir):
    """Resolve only the path-like Fermipy configuration fields."""
    config = copy.deepcopy(config)

    for key in ("evfile", "scfile", "ltcube"):
        if key in config.get("data", {}):
            config["data"][key] = resolve_path(config["data"][key], base_dir)

    for key in ("galdiff", "isodiff"):
        if key in config.get("model", {}):
            config["model"][key] = resolve_path(config["model"][key], base_dir)

    catalogs = config.get("model", {}).get("catalogs", [])
    config["model"]["catalogs"] = [
        resolve_path(path, base_dir) for path in catalogs
    ]

    return config


def apply_spatial_model_edit(fermipy_config, policy, outdir):
    """Replace XML catalog paths with policy-edited copies for this run."""
    if not policy or policy.get("enabled", True) is False:
        return fermipy_config

    policy = copy.deepcopy(policy)
    input_dir = outdir / "model_inputs"
    catalogs = fermipy_config.get("model", {}).get("catalogs", [])
    edited_catalogs = []
    for catalog in catalogs:
        catalog = Path(catalog)
        output_model = input_dir / default_output_path(catalog).name
        _, original_free_parameters, free_parameters = apply_model_policy(
            catalog, output_model, policy
        )
        logger.info("Model policy applied: %s -> %s", catalog, output_model)
        logger.info(
            "Free parameters in edited model: %d -> %d",
            original_free_parameters,
            free_parameters,
        )
        edited_catalogs.append(str(output_model))

    fermipy_config["model"]["catalogs"] = edited_catalogs
    return fermipy_config



def run_source_spatial_fit(
    gta,
    source_config,
    extension_defaults=None,
    localization_defaults=None,
):
    """Run one configured point-source localization or extension fit."""
    source_name = source_config["name"]
    spatial_model = source_config.get("spatial_model", "PointSource")

    if source_name not in gta.roi:
        logger.warning("Source not found in ROI, skipped: %s", source_name)
        return

    gta.fit(**source_config.get("fit", {}))

    if spatial_model == "PointSource":
        options = {
            "update": True,
            "make_plots": True,
            "fix_shape": True,
            "dtheta_max": 1.0,
            "nstep": 20,
        }
        options.update(localization_defaults or {})
        options.update(source_config.get("localization", {}))

        logger.info("Localizing point source: %s", source_name)
        localization_result = gta.localize(source_name, **options)

    else:
        options = {
            "spatial_model": spatial_model,
            "update": True,
            "make_plots": False,
            "make_tsmap": False,
            "fit_position": True,
            "fix_shape": True,
            "free_background": True,
            "width_min": 0.05,
            "width_max": 1.5,
            "width_nstep": 30,
        }
        options.update(extension_defaults or {})
        options.update(source_config.get("extension", {}))

        logger.info(
            "Fitting %s with %s spatial model.",
            source_name,
            spatial_model,
        )
        gta.extension(source_name, **options)
        localization_result = None

    gta.fit(**source_config.get("fit", {}))
    return localization_result


def main():
    args = parse_args()
    config_file = args.config.expanduser().resolve()

    with config_file.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    base_dir = config_file.parent
    fermipy_config = resolve_fermipy_paths(config["fermipy"], base_dir)

    outdir = Path(resolve_path(config["output"], base_dir))
    outdir.mkdir(parents=True, exist_ok=True)
    fermipy_config.setdefault("fileio", {})
    fermipy_config["fileio"]["outdir"] = str(outdir)
    fermipy_config = apply_spatial_model_edit(
        fermipy_config,
        load_model_policy(args.model_policy) if args.model_policy else None,
        outdir,
    )

    fit_options = fermipy_config.get("optimizer", {})
    extension_defaults = fermipy_config.get("extension", {})
    localization_defaults = fermipy_config.get("localize", {})
    sources = config.get("sources", [])

    output_config = config.get("outputs", {})

    logger.info("Configuration: %s", config_file)
    logger.info("Output directory: %s", outdir)
    logger.info("Configured spatial sources: %d", len(sources))

    gta = GTAnalysis(fermipy_config, logging={"verbosity": 3})
    gta.setup()
    gta.print_roi()
    gta.delete_sources(
        minmax_ts=[None, 1],
        exclude=["gll_iem_v07", "iso_P8R3_SOURCE_V3_v1"],
    )
    gta.fit()
    gta.print_params(True)
    gta.write_roi("fit_model", make_plots=True)

    localization_results = {}
    for source_config in sources:
        source_config = copy.deepcopy(source_config)
        source_config.setdefault("fit", fit_options)
        localization_result = run_source_spatial_fit(
            gta,
            source_config,
            extension_defaults,
            localization_defaults,
        )
        if localization_result is not None:
            localization_results[source_config["name"]] = localization_result
        
    write_final_products(
        gta,
        sources,
        outdir,
        output_config,
        localization_results,
    )
    logger.info("Spatial fitting completed.")


if __name__ == "__main__":
    logfile = configure_logger(logger, "../logs", "run_spatial.log")
    main()
