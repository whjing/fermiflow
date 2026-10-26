#!/usr/bin/env python3
"""Run the Kes 27 Fermitools workflow from a YAML project configuration."""

import argparse
import logging
import os
import os
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from fermi_target import FermiTarget, logger
from model_editor import apply_model_policy, default_output_path, load_model_policy
from utils import configure_logger, require_file, render_path


def energy_label(energy_mev):
    if energy_mev >= 1000 and energy_mev % 1000 == 0:
        return f"{energy_mev / 1000:g}GeV"
    return f"{energy_mev:g}MeV"



def load_project(config_file, emin_override=None, emax_override=None):
    config_file = require_file(config_file, "YAML configuration")
    with config_file.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    analysis = config["analysis"]
    paths = config["paths"]
    files = config["files"]
    target = analysis["target"]
    emin = float(emin_override if emin_override is not None else analysis["emin"])
    emax = float(emax_override if emax_override is not None else analysis["emax"])
    if emin <= 0 or emax <= emin:
        raise ValueError("Require 0 < emin < emax.")
    mapsize_deg = float(analysis["mapsize_deg"])
    binsz = float(analysis["binsz"])
    if mapsize_deg <= 0 or binsz <= 0:
        raise ValueError("Require mapsize_deg > 0 and binsz > 0.")

    context = {
        "target": target,
        "emin": emin,
        "emax": emax,
        "energy_label": energy_label(emin),
    }
    context["analysis_name"] = f"{target}_{context['energy_label']}"
    products_dir = render_path(paths["products_dir"], context)
    context["products_dir"] = str(products_dir)
    common_data_dir = render_path(
        paths.get("common_data_dir", paths.get("template_dir", "~/data/fermi")),
        context,
    )
    project_data_dir = render_path(paths.get("project_data_dir", "./data"), context)
    context["common_data_dir"] = str(common_data_dir)
    context["project_data_dir"] = str(project_data_dir)

    project = {
        "config_file": config_file,
        "target": target,
        "ra": float(analysis["ra"]),
        "dec": float(analysis["dec"]),
        "roi_radius": float(analysis["roi_radius"]),
        "emin": emin,
        "emax": emax,
        "mapsize_deg": mapsize_deg,
        "binsz": binsz,
        "zmax": int(analysis.get("zmax", 90)),
        "evclass": int(analysis.get("evclass", 128)),
        "evtype": int(analysis.get("evtype", 3)),
        "irfs": analysis.get("irfs", "P8R3_SOURCE_V3"),
        "analysis_name": context["analysis_name"],
        "energy_label": context["energy_label"],
        "common_data_dir": common_data_dir,
        "project_data_dir": project_data_dir,
        "rawdata_dir": render_path(paths["rawdata_dir"], context),
        "products_dir": products_dir,
        "log_dir": render_path(paths.get("log_dir", "../logs"), context),
        "ltcube": (
            render_path(files["ltcube"], context)
            if files.get("ltcube") is not None
            else None
        ),
        "catalog": files["catalog"],
        "galactic": files["galactic"],
        "isotropic": files["isotropic"],
        "base_gti": (
            render_path(files["base_gti"], context)
            if files.get("base_gti") is not None
            else None
        ),
        "sed_model": (
            render_path(files["sed_model"], context)
            if files.get("sed_model") is not None
            else None
        ),
    }
    return project


def edited_model(project, input_model, model_policy):
    """Create and return a policy-edited XML when a policy was supplied."""
    input_model = require_file(input_model, "Input model")
    if not model_policy:
        return input_model

    policy = dict(model_policy)
    radial = policy.get("radial")
    if radial and "center" not in radial:
        radial = dict(radial)
        radial["center"] = {"ra": project["ra"], "dec": project["dec"]}
        policy["radial"] = radial

    output_model = default_output_path(input_model)
    summary = apply_model_policy(input_model, output_model, policy)
    logger.info("Model policy applied: %s -> %s", input_model, output_model)
    logger.info("Model policy changed %d parameters.", sum(item[2] for item in summary))
    return output_model


def make_target(
    project,
    name,
    output_dir,
    eminBin=None,
    emaxBin=None,
    input_model=None,
    require_ltcube=False,
):
    path_ltcube = project["ltcube"]
    if path_ltcube is not None and require_ltcube:
        path_ltcube = require_file(path_ltcube, "Livetime cube")

    target = FermiTarget(
        name=name,
        c_ra=project["ra"],
        c_dec=project["dec"],
        rad=project["roi_radius"],
        emin=project["emin"] if eminBin is None else eminBin,
        emax=project["emax"] if emaxBin is None else emaxBin,
        zmax=project["zmax"],
        evclass=project["evclass"],
        evtype=project["evtype"],
        mapsize_deg=project["mapsize_deg"],
        binsz=project["binsz"],
        dir_template=str(project["common_data_dir"]),
        dir_rawdata=str(project["rawdata_dir"]),
        dir_products=str(output_dir),
        file_catalog=project["catalog"],
        file_diffuse=project["galactic"],
        file_pointsrc=project["isotropic"],
        irfs=project["irfs"],
        path_ltcube=str(path_ltcube) if path_ltcube is not None else None,
        path_model_input=str(input_model) if input_model else None,
    )
    return target


def require_full_band_products(project):
    products = project["products_dir"]
    name = project["analysis_name"]
    require_file(products / f"{name}_ccube.fits", "Full-band CCUBE")
    require_file(products / f"{name}_bexpmap.fits", "Full-band exposure map")


def run_prepare(project):
    target = make_target(project, project["analysis_name"], project["products_dir"])

    target.exam_rawdata()
    target.export_evtlist()
    target.run_gtselect()
    target.run_gtmktime()

    # check if the livetime cube already exists
    if os.path.isfile(target.path_ltcube):
        logger.info(f"Reusing configured livetime cube: {target.path_ltcube}")
    else:
        logger.info("Generating livetime cube: %s", target.path_ltcube)
        target.run_gtltcube()

    target.run_gtbin_cmap()
    target.run_gtbin_ccube()
    target.run_gtexpcube2()
    target.run_make4FGLxml()

    return target

def run_like(project, input_model, model_policy=None):
    require_full_band_products(project)
    input_model = edited_model(project, input_model, model_policy)
    target = make_target(
        project,
        project["analysis_name"],
        project["products_dir"],
        input_model=input_model,
        require_ltcube=True,
    )
    return target.run_gtsrcmap_gtlike2(str(input_model), source_name=project["target"])


def run_sed_bin(project, nbins, bin_index, model_policy=None):
    if nbins < 1 or not 0 <= bin_index < nbins:
        raise ValueError(f"--ibin must be between 0 and {nbins - 1}.")

    require_file(project["ltcube"], "Livetime cube")
    base_gti = require_file(project["base_gti"], "Full-band GTI")
    base_model = require_file(project["sed_model"], "SED base model")
    edges = np.geomspace(project["emin"], project["emax"], nbins + 1)
    emin, emax = float(edges[bin_index]), float(edges[bin_index + 1])
    number = bin_index + 1
    outdir, _, _ = sed_bin_output_dir(project, nbins, bin_index)
    if outdir.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing output directory: {outdir}"
        )
    outdir.mkdir(parents=True)

    input_model = outdir / f"{project['target']}_sed_{nbins}bin{number:02d}_input.xml"
    shutil.copy2(base_model, input_model)
    input_model = edited_model(project, input_model, model_policy)
    target = make_target(
        project,
        f"{project['target']}_{nbins}bin{number:02d}",
        outdir,
        emin,
        emax,
        input_model,
    )
    target.path_gti = str(base_gti)
    target.run_gtselect(startfrom="gti")
    target.path_gti = target.path_filtered
    target.run_gtbin_ccube()
    target.run_gtexpcube2(cmap=target.path_ccube)
    return target.run_gtsrcmap_gtlike2(str(input_model), source_name=project["target"])


def sed_bin_output_dir(project, nbins, bin_index):
    edges = np.geomspace(project["emin"], project["emax"], nbins + 1)
    emin, emax = float(edges[bin_index]), float(edges[bin_index + 1])
    tag = f"bin_{bin_index + 1:02d}_{emin * 1e-3:.2f}-{emax * 1e-3:.2f}GeV".replace(".", "p")
    return (project["products_dir"] / tag).resolve(), emin, emax


def run_sed_bin_fit(project, nbins, bin_index, input_model, model_policy=None):
    """Refit an existing SED bin without repeating event selection."""
    if nbins < 1 or not 0 <= bin_index < nbins:
        raise ValueError(f"--ibin must be between 0 and {nbins - 1}.")

    input_model = edited_model(project, input_model, model_policy)
    require_file(project["ltcube"], "Livetime cube")
    outdir, emin, emax = sed_bin_output_dir(project, nbins, bin_index)
    if not outdir.is_dir():
        raise FileNotFoundError(
            f"SED bin products not found: {outdir}. "
            "Run bin mode once without --input-model first."
        )

    target_name = f"{project['target']}_{nbins}bin{bin_index + 1:02d}"
    require_file(outdir / f"{target_name}_ccube.fits", f"{nbins}-bin SED CCUBE")
    require_file(
        outdir / f"{target_name}_bexpmap.fits", f"{nbins}-bin SED exposure map"
    )

    model_copy = outdir / f"{target_name}_input.xml"
    if input_model.resolve() != model_copy.resolve():
        shutil.copy2(input_model, model_copy)

    target = make_target(
        project,
        target_name,
        outdir,
        emin,
        emax,
        model_copy,
    )
    return target.run_gtsrcmap_gtlike2(str(model_copy), source_name=project["target"])


def run_tsmap(project, input_model, size, binsz, model_policy=None):
    require_full_band_products(project)
    input_model = edited_model(project, input_model, model_policy)
    if size <= 0 or binsz <= 0:
        raise ValueError("--size and --binsz must be positive.")
    target = make_target(
        project,
        project["analysis_name"],
        project["products_dir"],
        input_model=input_model,
        require_ltcube=True,
    )
    return target.run_gttsmap(
        path_model=str(input_model), xsize=size, ysize=size, binsz=binsz
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Kes 27 Fermitools workflow.")
    parser.add_argument("--config", type=Path, required=True, help="Project YAML file.")
    parser.add_argument(
        "--mode", required=True, choices=("prepare", "like", "bin", "bin-fit", "tsmap")
    )
    parser.add_argument(
        "--input-model",
        type=Path,
        help="Input model for like/tsmap, or an updated model to refit an existing bin.",
    )
    parser.add_argument("--nbins", type=int, help="Required for bin mode.")
    parser.add_argument(
        "--ibin",
        type=int,
        help="One-based SED bin number; required for bin and bin-fit modes.",
    )
    parser.add_argument(
        "--size", type=float, help="Square TS-map size in degrees; required for tsmap."
    )
    parser.add_argument(
        "--binsz", type=float, help="TS-map pixel size in degrees; required for tsmap."
    )
    parser.add_argument(
        "--emin", type=float, help="Temporary full-band lower-energy override in MeV."
    )
    parser.add_argument(
        "--emax", type=float, help="Temporary full-band upper-energy override in MeV."
    )
    parser.add_argument(
        "--log-name", help="Log basename; timestamp is appended automatically."
    )
    parser.add_argument(
        "--model-policy", type=Path,
        help="Optional standalone YAML policy used to create an edited XML before fitting.",
    )
    args = parser.parse_args()

    if args.mode in {"like", "tsmap"} and args.input_model is None:
        parser.error("--input-model is required for like and tsmap modes.")
    if args.mode in {"bin", "bin-fit"} and (args.nbins is None or args.ibin is None):
        parser.error("--nbins and --ibin are required for bin mode.")
    if args.mode in {"bin", "bin-fit"} and args.ibin is not None:
        if args.ibin < 1 or (args.nbins is not None and args.ibin > args.nbins):
            parser.error(f"--ibin must be between 1 and {args.nbins}.")
    if args.mode == "bin-fit" and args.input_model is None:
        parser.error("--input-model is required for bin-fit mode.")
    if args.mode == "tsmap" and (args.size is None or args.binsz is None):
        parser.error("--size and --binsz are required for tsmap mode.")
    return args


def main():
    args = parse_args()
    project = load_project(args.config, args.emin, args.emax)
    model_policy = load_model_policy(args.model_policy) if args.model_policy else None
    log_name = args.log_name or f"{args.mode}_{project['energy_label']}"
    log_file = configure_logger(logger, project["log_dir"], log_name)
    logger.info("Log file: %s", log_file)
    logger.info("Command: %s", shlex.join(sys.argv))
    logger.info("Config: %s", project["config_file"])
    logger.info("Mode: %s", args.mode)
    logger.info("Energy range: %g--%g MeV", project["emin"], project["emax"])
    if args.input_model is not None:
        logger.info("Input model: %s", args.input_model.expanduser().resolve())
    if args.model_policy is not None:
        logger.info("Model policy: %s", args.model_policy.expanduser().resolve())

    if args.mode == "prepare":
        run_prepare(project)
    elif args.mode == "like":
        run_like(project, args.input_model, model_policy)
    elif args.mode == "bin":
        run_sed_bin(project, args.nbins, args.ibin - 1, model_policy)
    elif args.mode == "bin-fit":
        run_sed_bin_fit(project, args.nbins, args.ibin - 1, args.input_model, model_policy)
    elif args.mode == "tsmap":
        run_tsmap(project, args.input_model, args.size, args.binsz, model_policy)
    else:
        logger.error("Unknown mode: %s", args.mode)


if __name__ == "__main__":
    main()
