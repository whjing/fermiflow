# %%
#!/usr/bin/env python3
"""Plot g328, pt, and extend SEDs from gtlike MINUIT result files.

SED points:
    Read directly from each bin's *_minuit_results.dat file.

Spectral curves:
    Read from full-band PL and LogParabola *_minuit.xml models.
"""

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ============================================================================
# Settings
# ============================================================================

PRODUCTS_DIR = Path("../products_100MeV")
RESULT_PATTERN = "bin_*/*_minuit_results.dat"

SOURCES = ["g328", "pt", "extend"]

TS_THRESHOLD = 5.0
MEV_TO_ERG = 1.602176634e-6

# Full-band fitted XML models for overlaid spectral curves.
PL_MODEL = Path("../products_100MeV/g328_model-1_g-pl_minuit.xml")
LOGPARABOLA_MODEL = Path(
    "../products_100MeV/g328_model-1_g-logpl_minuit.xml"
)

OUTPUT_PNG = PRODUCTS_DIR / "sed_6bin" / "g328_pt_extend_sed_from_dat.png"

COLORS = {
    "g328": "tab:red",
    "pt": "tab:blue",
    "extend": "tab:green",
}

NUMBER_PATTERN = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


# ============================================================================
# Read MINUIT result files
# ============================================================================

def newest_result_file_per_bin():
    """
    Find all *_minuit_results.dat files and retain only the newest result
    file in every bin directory.
    """
    candidates = list(PRODUCTS_DIR.glob(RESULT_PATTERN))

    if not candidates:
        raise FileNotFoundError(
            f"No files found with pattern: {PRODUCTS_DIR / RESULT_PATTERN}"
        )

    newest = {}

    for result_file in candidates:
        bin_dir = result_file.parent.resolve()

        if (
            bin_dir not in newest
            or result_file.stat().st_mtime > newest[bin_dir].stat().st_mtime
        ):
            newest[bin_dir] = result_file

    return sorted(newest.values())


def first_number(text):
    """Return the first valid floating-point number in text."""
    match = NUMBER_PATTERN.search(str(text))

    if match is None:
        return np.nan

    return float(match.group())


def parse_number_and_error(value_text):
    """
    Parse values such as:

        '0.852256 +/- 38.252'
        '1.88324e-10 +/- 8.45239e-09'
        '3000'
    """
    text = str(value_text).strip()

    parts = re.split(r"\s*(?:\+/-|±)\s*", text, maxsplit=1)

    value = first_number(parts[0])
    error = first_number(parts[1]) if len(parts) == 2 else np.nan

    return value, error


def read_results_dat(result_file):
    """
    Read a gtlike *_minuit_results.dat file.

    Expected example:

    'g328': {'Prefactor': '0.852256 +/- 38.252',
             'Index': '2.20143',
             'Scale': '3000',
             'TS value': '0.123276',
             'Flux': '1.88324e-10 +/- 8.45239e-09',
            },
    """
    text = result_file.read_text(encoding="utf-8", errors="replace").strip()

    # These files are commonly dictionary fragments without outer braces.
    wrapped_text = text if text.startswith("{") else "{" + text + "}"

    try:
        return ast.literal_eval(wrapped_text)

    except (SyntaxError, ValueError):
        # Fallback parser for slightly irregular dictionary-like formatting.
        data = {}

        source_blocks = re.findall(
            r"['\"]([^'\"]+)['\"]\s*:\s*\{(.*?)\}\s*,?",
            text,
            flags=re.DOTALL,
        )

        for source_name, block in source_blocks:
            parameters = {}

            for key, value in re.findall(
                r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]*)['\"]",
                block,
            ):
                parameters[key] = value

            data[source_name] = parameters

        if not data:
            raise ValueError(f"Cannot parse result file: {result_file}")

        return data


def parse_energy_range_from_directory(result_file):
    """
    Read energy edges from the parent directory name.

    Supported directory examples:
        bin_03_1p71-7p07GeV
        bin_06_120p91-500p00GeV
        bin_01_100p00-413p52MeV
    """
    directory_name = result_file.parent.name

    match = re.search(
        r"bin_\d+_([0-9p]+)-([0-9p]+)(MeV|GeV)$",
        directory_name,
        flags=re.IGNORECASE,
    )

    if match is None:
        raise ValueError(
            f"Cannot read energy range from directory: {directory_name}"
        )

    emin_text, emax_text, unit = match.groups()

    emin = float(emin_text.replace("p", "."))
    emax = float(emax_text.replace("p", "."))

    if unit.lower() == "gev":
        emin *= 1e3
        emax *= 1e3

    return emin, emax


def parse_source_result(source_data, emin_mev, emax_mev):
    """Extract spectral parameters, TS, flux, and flux uncertainty."""
    result = {
        "emin_mev": emin_mev,
        "emax_mev": emax_mev,
        "ts": np.nan,
        "photon_flux": np.nan,
        "photon_flux_err": np.nan,
        "spectrum_type": None,
        "parameters": {},
    }

    if not source_data:
        return result

    if "TS value" in source_data:
        result["ts"], _ = parse_number_and_error(source_data["TS value"])

    if "Flux" in source_data:
        result["photon_flux"], result["photon_flux_err"] = (
            parse_number_and_error(source_data["Flux"])
        )

    for parameter_name in [
        "Prefactor",
        "Index",
        "Scale",
        "norm",
        "alpha",
        "beta",
        "Eb",
    ]:
        if parameter_name in source_data:
            value, _ = parse_number_and_error(source_data[parameter_name])
            result["parameters"][parameter_name] = value

    parameters = result["parameters"]

    if {"Prefactor", "Index", "Scale"} <= parameters.keys():
        result["spectrum_type"] = "PowerLaw"

    elif {"norm", "alpha", "beta", "Eb"} <= parameters.keys():
        result["spectrum_type"] = "LogParabola"

    return result


# ============================================================================
# Calculate SED points from MINUIT result values
# ============================================================================

def bin_spectral_shape(energy_mev, spectrum_type, parameters):
    """
    Return spectral shape without absolute normalization.

    The final normalization is set by the photon Flux recorded in the
    corresponding *_minuit_results.dat file.
    """
    energy_mev = np.asarray(energy_mev, dtype=float)

    if spectrum_type == "PowerLaw":
        # gtlike result files report positive photon index Gamma.
        return (energy_mev / parameters["Scale"]) ** (-parameters["Index"])

    if spectrum_type == "LogParabola":
        log_ratio = np.log(energy_mev / parameters["Eb"])

        return np.exp(
            -parameters["alpha"] * log_ratio
            - parameters["beta"] * log_ratio**2
        )

    raise ValueError(f"Unsupported bin spectrum: {spectrum_type}")


def calculate_sed_point(result):
    """
    Calculate E^2 dN/dE at the logarithmic bin centre.

    The bin spectrum is normalized to reproduce the fitted photon flux:
        Flux = integral[dN/dE dE].

    The y-axis uncertainty is propagated from the fitted flux uncertainty.
    """
    emin = result["emin_mev"]
    emax = result["emax_mev"]

    photon_flux = result["photon_flux"]
    photon_flux_err = result["photon_flux_err"]

    spectrum_type = result["spectrum_type"]
    parameters = result["parameters"]

    if (
        not np.isfinite(photon_flux)
        or photon_flux <= 0
        or spectrum_type is None
    ):
        return np.nan, np.nan, np.nan

    energy_grid = np.geomspace(emin, emax, 2000)
    shape = bin_spectral_shape(energy_grid, spectrum_type, parameters)
    shape_integral = np.trapz(shape, energy_grid)

    if not np.isfinite(shape_integral) or shape_integral <= 0:
        return np.nan, np.nan, np.nan

    normalization = photon_flux / shape_integral
    energy_center = np.sqrt(emin * emax)

    dnde_center = normalization * bin_spectral_shape(
        energy_center,
        spectrum_type,
        parameters,
    )

    sed_value = energy_center**2 * dnde_center * MEV_TO_ERG

    if np.isfinite(photon_flux_err) and photon_flux_err >= 0:
        sed_error = sed_value * photon_flux_err / photon_flux
    else:
        sed_error = np.nan

    return energy_center, sed_value, sed_error


def log_safe_yerr(value, error):
    """
    Make a symmetric error safe for display on a logarithmic y-axis.

    If error > value, the lower endpoint would be non-positive. The lower
    bar is clipped just above zero; the full upper uncertainty is preserved.
    """
    if not np.isfinite(error) or error < 0:
        return None

    return np.array([
        [min(error, 0.98 * value)],
        [error],
    ])


# ============================================================================
# Read full-band spectral curves from XML
# ============================================================================

def xml_parameter_values(spectrum):
    """Read physical XML parameter values: value multiplied by scale."""
    values = {}

    for parameter in spectrum.findall("parameter"):
        values[parameter.get("name")] = (
            float(parameter.get("value", 0.0))
            * float(parameter.get("scale", 1.0))
        )

    return values


def read_full_band_spectrum(xml_file, source_name):
    """Read one source spectrum from a fitted full-band XML model."""
    tree = ET.parse(xml_file)
    source = tree.getroot().find(f"./source[@name='{source_name}']")

    if source is None:
        return None, None

    spectrum = source.find("spectrum")

    return spectrum.get("type"), xml_parameter_values(spectrum)


def full_band_dnde(energy_mev, spectrum_type, parameters):
    """Evaluate dN/dE from the full-band fitted XML model."""
    energy_mev = np.asarray(energy_mev, dtype=float)

    if spectrum_type == "PowerLaw":
        return (
            parameters["Prefactor"]
            * (energy_mev / parameters["Scale"]) ** parameters["Index"]
        )

    if spectrum_type == "LogParabola":
        log_ratio = np.log(energy_mev / parameters["Eb"])

        return parameters["norm"] * np.exp(
            -parameters["alpha"] * log_ratio
            - parameters["beta"] * log_ratio**2
        )

    raise ValueError(f"Unsupported full-band spectrum: {spectrum_type}")


# ============================================================================
# Collect results
# ============================================================================

def collect_all_results():
    """Read final MINUIT results and sort each source by energy."""
    rows = {source: [] for source in SOURCES}

    result_files = newest_result_file_per_bin()

    print("Result files used")
    print("-" * 100)

    for result_file in result_files:
        emin, emax = parse_energy_range_from_directory(result_file)
        results_data = read_results_dat(result_file)

        print(
            f"{emin:11.3f}-{emax:11.3f} MeV   "
            f"{result_file}"
        )

        for source_name in SOURCES:
            row = parse_source_result(
                results_data.get(source_name, {}),
                emin,
                emax,
            )

            row["source"] = source_name
            row["result_file"] = result_file
            rows[source_name].append(row)

    for source_name in SOURCES:
        rows[source_name].sort(key=lambda row: row["emin_mev"])

    return rows


# ============================================================================
# Plot
# ============================================================================

def plot_source_sed(ax, source_name, rows, pl_model, logparabola_model):
    """Plot one source's SED points and full-band PL/LogParabola curves."""
    energy_curve = np.geomspace(100.0, 500000.0, 500)

    for model, linestyle, label in [
        (pl_model, "-", "Full-band PL"),
        (logparabola_model, "--", "Full-band LogParabola"),
    ]:
        spectrum_type, parameters = model

        if spectrum_type is None:
            continue

        sed_curve = (
            energy_curve**2
            * full_band_dnde(energy_curve, spectrum_type, parameters)
            * MEV_TO_ERG
        )

        ax.plot(
            energy_curve * 1e-3,
            sed_curve,
            color="black",
            linestyle=linestyle,
            linewidth=1.8,
            zorder=2,
            label=label,
        )

    detection_labeled = False
    low_ts_labeled = False
    missing_ts_labeled = False

    for row in rows:
        energy_center, sed_value, sed_error = calculate_sed_point(row)

        if not np.isfinite(sed_value):
            print(
                f"Skip {source_name} in {row['result_file'].name}: "
                "missing Flux or spectrum parameters."
            )
            continue

        ts = row["ts"]

        emin_gev = row["emin_mev"] * 1e-3
        emax_gev = row["emax_mev"] * 1e-3
        center_gev = energy_center * 1e-3

        xerr = np.array([
            [center_gev - emin_gev],
            [emax_gev - center_gev],
        ])

        yerr = log_safe_yerr(sed_value, sed_error)

        if np.isfinite(ts) and ts >= TS_THRESHOLD:
            marker = "o"
            markerfacecolor = COLORS[source_name]
            label = "TS ≥ 5" if not detection_labeled else None
            detection_labeled = True

        elif np.isfinite(ts):
            # This is a visual fitted value, not a formal upper limit.
            marker = "v"
            markerfacecolor = "none"
            label = "TS < 5 (fit value)" if not low_ts_labeled else None
            low_ts_labeled = True

        else:
            marker = "s"
            markerfacecolor = "none"
            label = "TS unavailable" if not missing_ts_labeled else None
            missing_ts_labeled = True

        ax.errorbar(
            center_gev,
            sed_value,
            xerr=xerr,
            yerr=yerr,
            fmt=marker,
            color=COLORS[source_name],
            markerfacecolor=markerfacecolor,
            markeredgecolor=COLORS[source_name],
            capsize=3,
            zorder=4,
            label=label,
        )

        ts_text = f"TS={ts:.1f}" if np.isfinite(ts) else "TS=--"

        ax.annotate(
            ts_text,
            (center_gev, sed_value),
            xytext=(4, 5),
            textcoords="offset points",
            fontsize=7,
            color=COLORS[source_name],
        )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title(source_name)
    ax.set_xlabel("Energy [GeV]")
    ax.grid(alpha=0.25, which="both")
    ax.legend(fontsize=8, loc="best")


def main():
    all_rows = collect_all_results()

    pl_models = {
        source: read_full_band_spectrum(PL_MODEL, source)
        for source in SOURCES
    }

    logparabola_models = {
        source: read_full_band_spectrum(LOGPARABOLA_MODEL, source)
        for source in SOURCES
    }

    print("\nFinal MINUIT values read from results.dat")
    print("-" * 115)

    for source_name in SOURCES:
        print(f"\n{source_name}")

        for row in all_rows[source_name]:
            ts_text = f"{row['ts']:.3f}" if np.isfinite(row["ts"]) else "--"

            flux_text = "--"
            if np.isfinite(row["photon_flux"]):
                flux_text = f"{row['photon_flux']:.3e}"

                if np.isfinite(row["photon_flux_err"]):
                    flux_text += f" +/- {row['photon_flux_err']:.3e}"

            print(
                f"{row['emin_mev']:11.3f}-{row['emax_mev']:11.3f} MeV  "
                f"TS={ts_text:>8}  "
                f"Flux={flux_text:<30}  "
                f"{row['result_file'].name}"
            )

    fig, axes = plt.subplots(
        1,
        3,
        figsize=(15, 4.8),
        sharex=True,
        sharey=True,
    )

    for ax, source_name in zip(axes, SOURCES):
        plot_source_sed(
            ax,
            source_name,
            all_rows[source_name],
            pl_models[source_name],
            logparabola_models[source_name],
        )

    axes[0].set_ylabel(r"$E^2 dN/dE$ [erg cm$^{-2}$ s$^{-1}$]")

    fig.suptitle(
        "G328 field: SEDs from gtlike MINUIT result files",
        y=1.02,
        fontsize=14,
    )

    fig.tight_layout()

    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PNG, dpi=250, bbox_inches="tight")

    plt.show()

    print(f"\nSaved: {OUTPUT_PNG.resolve()}")


if __name__ == "__main__":
    main()

# %%