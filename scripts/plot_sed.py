# %%
#!/usr/bin/env python3
"""Plot the Kes 27 six-bin SED with full-band PL and LogParabola models."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import shlex
import stat


TARGET = "kes27"
TS_THRESHOLD = 5.0
MEV_TO_ERG = 1.602176634e-6

# ----------------------------------------------------------------------
# Six SED fitting logs
# ----------------------------------------------------------------------

LOG_FILES = [
    Path("../logs/sed_6bin_mod/sed-6bin-mod-01-1992851.log"),
    Path("../logs/sed_6bin_mod/sed-6bin-mod-02-1992852.log"),
    Path("../logs/sed_6bin_mod/sed-6bin-mod-03-1992853.log"),
    Path("../logs/sed_6bin_mod/sed-6bin-mod-04-1992854.log"),
    Path("../logs/sed_6bin_mod/sed-6bin-mod-05-1992973.log"),
    Path("../logs/sed_6bin_mod/sed-6bin-mod-06-1992856.log"),
]

# ----------------------------------------------------------------------
# Full-band fitted models: edit these two paths if your filenames differ
# ----------------------------------------------------------------------

PL_MODEL = Path("../products_100MeV/kes27_point-pl-1_minuit.xml")
LOGPARABOLA_MODEL = Path("../products_100MeV/kes27_point-logpl-1_minuit.xml")

OUTPUT_DIR = Path("../products_100MeV/sed_6bin")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PNG = OUTPUT_DIR / "kes27_sed_6bin_pl_logparabola.png"

def write_submit_script(model_files):
    """
    Generate one shell script that submits one Slurm SED job per modified XML.
    The generated shell script does not submit anything until you run it.
    """
    script_dir = Path.cwd().resolve()
    run_script = (script_dir / "run_kes27.py").resolve()
    config_file = (script_dir / "kes27_100MeV.yaml").resolve()

    if not run_script.is_file():
        raise FileNotFoundError(f"run_kes27.py not found: {run_script}")

    if not config_file.is_file():
        raise FileNotFoundError(f"YAML config not found: {config_file}")

    nbins = len(model_files)
    submit_script = script_dir / f"submit_sed_{nbins}bin_mod.sh"

    model_lines = "\n".join(
        f"    {shlex.quote(str(model_file.resolve()))}"
        for model_file in model_files
    )

    content = f"""#!/usr/bin/env bash
# Submit SED-bin jobs using the cleaned -mod_input.xml models.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
RUN_SCRIPT={shlex.quote(str(run_script))}
CONFIG_FILE={shlex.quote(str(config_file))}
NBINS={nbins}

SBATCH_DIR="${{SBATCH_DIR:-$SCRIPT_DIR/../sbatch/sed_${{NBINS}}bin_mod}}"
LOG_DIR="${{LOG_DIR:-$SCRIPT_DIR/../logs/sed_${{NBINS}}bin_mod}}"
CONDA_ENV="${{CONDA_ENV:-fermi}}"

NODES=(c001 c002 c003 c004 c005)

MODELS=(
{model_lines}
)

if command -v conda >/dev/null 2>&1; then
    CONDA_SH="${{CONDA_SH:-$(conda info --base)/etc/profile.d/conda.sh}}"
else
    CONDA_SH="${{CONDA_SH:-/share/home/whjing/miniforge3/etc/profile.d/conda.sh}}"
fi

[[ -f "$RUN_SCRIPT" ]] || {{ echo "Missing run script: $RUN_SCRIPT" >&2; exit 1; }}
[[ -f "$CONFIG_FILE" ]] || {{ echo "Missing YAML config: $CONFIG_FILE" >&2; exit 1; }}
[[ -f "$CONDA_SH" ]] || {{ echo "Missing conda.sh: $CONDA_SH" >&2; exit 1; }}

mkdir -p "$SBATCH_DIR" "$LOG_DIR"
SBATCH_DIR="$(realpath -e "$SBATCH_DIR")"
LOG_DIR="$(realpath -e "$LOG_DIR")"

for index in "${{!MODELS[@]}}"; do
    ibin=$((index + 1))
    input_model="${{MODELS[index]}}"
    node="${{NODES[index % ${{#NODES[@]}}]}}"
    tag="sed-${{NBINS}}bin-mod-$(printf '%02d' "$ibin")"
    job_script="$SBATCH_DIR/${{tag}}.sbatch"

    [[ -f "$input_model" ]] || {{
        echo "Missing modified XML: $input_model" >&2
        exit 1
    }}

    cat > "$job_script" <<EOF
#!/usr/bin/env bash
#SBATCH --job-name=${{tag}}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --nodelist=${{node}}
#SBATCH --output=${{LOG_DIR}}/%x-%j.log
#SBATCH --error=${{LOG_DIR}}/%x-%j.log

set -eo pipefail

source "${{CONDA_SH}}"
conda activate "${{CONDA_ENV}}"

echo "========================================"
echo "Job ID:      ${{SLURM_JOB_ID}}"
echo "Node:        $(hostname)"
echo "SED bin:     ${{ibin}}/${{NBINS}}"
echo "Input model: ${{input_model}}"
echo "========================================"

cd "${{SCRIPT_DIR}}"

exec "$(command -v python)" "${{RUN_SCRIPT}}" \\
    --config "${{CONFIG_FILE}}" \\
    --mode bin-fit \\
    --nbins "${{NBINS}}" \\
    --ibin "${{ibin}}" \\
    --input-model "${{input_model}}"
EOF

    chmod 750 "$job_script"

    job_id="$(sbatch --parsable "$job_script")"
    echo "Submitted ${{job_id%%;*}}: ${{tag}} on ${{node}}"
done
"""

    submit_script.write_text(content, encoding="utf-8")
    submit_script.chmod(submit_script.stat().st_mode | stat.S_IXUSR)

    print(f"\\nCreated submission script: {submit_script}")
    print("Submit all modified SED jobs with:")
    print(f"  bash {submit_script}")

    return submit_script


def parameter_value(parameter):
    """Return physical parameter value = XML value × scale."""
    return float(parameter.get("value")) * float(parameter.get("scale", "1"))

def read_spectrum(xml_file):
    """Read Kes 27 spectrum values and 1-sigma errors from fitted XML."""
    tree = ET.parse(xml_file)
    root = tree.getroot()

    source = root.find(f"./source[@name='{TARGET}']")
    if source is None:
        raise ValueError(f"Cannot find source '{TARGET}' in {xml_file}")

    spectrum = source.find("spectrum")
    parameters = {}
    errors = {}

    for parameter in spectrum.findall("parameter"):
        name = parameter.get("name")
        scale = float(parameter.get("scale", "1"))

        parameters[name] = float(parameter.get("value")) * scale

        if parameter.get("error") is not None:
            errors[name] = abs(float(parameter.get("error")) * scale)

    return spectrum.get("type"), parameters, errors


def make_butterfly(energy_mev, spectrum_type, parameters, errors, nsample=3000):
    """
    Create an approximate 68% spectral band.

    Parameter correlations are ignored because minuit.xml does not retain
    the covariance matrix.  This is not yet a formal covariance butterfly.
    """
    rng = np.random.default_rng(20261012)
    samples = []

    for _ in range(nsample):
        sampled = parameters.copy()

        for name, error in errors.items():
            if error > 0:
                sampled[name] = rng.normal(parameters[name], error)

        # Normalization must remain positive.
        if spectrum_type == "PowerLaw" and sampled["Prefactor"] <= 0:
            continue

        if spectrum_type == "LogParabola" and sampled["norm"] <= 0:
            continue

        sed = (
            energy_mev**2
            * dnde(energy_mev, spectrum_type, sampled)
            * MEV_TO_ERG
        )

        if np.all(np.isfinite(sed)) and np.all(sed > 0):
            samples.append(sed)

    samples = np.asarray(samples)

    if len(samples) < 100:
        raise RuntimeError("Too few valid spectral samples for uncertainty band.")

    lower = np.percentile(samples, 16, axis=0)
    upper = np.percentile(samples, 84, axis=0)

    return lower, upper


def dnde(energy_mev, spectrum_type, parameters):
    """Evaluate dN/dE in ph cm^-2 s^-1 MeV^-1 from an XML spectrum."""
    energy_mev = np.asarray(energy_mev, dtype=float)

    if spectrum_type == "PowerLaw":
        prefactor = parameters["Prefactor"]
        index = parameters["Index"]
        scale = parameters["Scale"]
        return prefactor * (energy_mev / scale) ** index

    if spectrum_type == "LogParabola":
        norm = parameters["norm"]
        alpha = parameters["alpha"]
        beta = parameters["beta"]
        eb = parameters["Eb"]
        log_ratio = np.log(energy_mev / eb)
        return norm * np.exp(-alpha * log_ratio - beta * log_ratio**2)

    raise ValueError(f"Unsupported spectrum type: {spectrum_type}")


def mean_energy_mev(emin_mev, emax_mev, spectrum_type, parameters):
    """
    Mean photon energy for the full-band PL model.

    Used only to convert an integrated photon-flux UL to an approximate
    energy-flux UL in each SED bin.
    """
    energy = np.geomspace(emin_mev, emax_mev, 2000)
    shape = dnde(energy, spectrum_type, parameters)

    photon_integral = np.trapz(shape, energy)
    energy_integral = np.trapz(energy * shape, energy)

    return energy_integral / photon_integral


def parse_sed_log(log_file):
    """Read Kes 27 TS, energy flux, errors, and photon-flux UL from one log."""
    text = log_file.read_text(encoding="utf-8", errors="replace")

    ts_match = re.search(rf"TS\({TARGET}\):\s*([-+0-9.eE]+)", text)

    energy_flux_match = re.search(
        r"Energy flux\s*\(([-+0-9.eE]+)-([-+0-9.eE]+)\s*MeV\):\s*"
        r"\(\s*([-+0-9.eE]+)\s*(?:±|\+/-)\s*([-+0-9.eE]+)\s*\)",
        text,
    )

    photon_ul_match = re.search(
        r"95%\s+photon-flux\s+UL\s*"
        r"\(([-+0-9.eE]+)-([-+0-9.eE]+)\s*MeV\):\s*"
        r"([-+0-9.eE]+)",
        text,
    )

    result = {
        "ts": float(ts_match.group(1)) if ts_match else np.nan,
        "emin_mev": np.nan,
        "emax_mev": np.nan,
        "energy_flux": np.nan,
        "energy_flux_err": np.nan,
        "photon_flux_ul": np.nan,
    }

    if energy_flux_match:
        result["emin_mev"] = float(energy_flux_match.group(1))
        result["emax_mev"] = float(energy_flux_match.group(2))
        result["energy_flux"] = float(energy_flux_match.group(3))
        result["energy_flux_err"] = float(energy_flux_match.group(4))

    if photon_ul_match:
        result["emin_mev"] = float(photon_ul_match.group(1))
        result["emax_mev"] = float(photon_ul_match.group(2))
        result["photon_flux_ul"] = float(photon_ul_match.group(3))

    return result


def main():
    pl_type, pl_parameters, pl_errors = read_spectrum(PL_MODEL)
    lp_type, lp_parameters, lp_errors = read_spectrum(LOGPARABOLA_MODEL)

    rows = []

    for bin_number, log_file in enumerate(LOG_FILES, start=1):
        log_file = log_file.expanduser().resolve()

        if not log_file.is_file():
            print(f"Skip bin {bin_number}: log not found: {log_file}")
            continue

        values = parse_sed_log(log_file)

        if not np.isfinite(values["emin_mev"]):
            print(f"Skip bin {bin_number}: no Kes 27 summary found in {log_file}")
            continue

        emin = values["emin_mev"]
        emax = values["emax_mev"]
        energy_center = np.sqrt(emin * emax)
        delta_log_energy = np.log(emax / emin)

        row = {
            "bin": bin_number,
            "emin_mev": emin,
            "emax_mev": emax,
            "energy_center_mev": energy_center,
            "ts": values["ts"],
            "sed_value": np.nan,
            "sed_error": np.nan,
            "sed_ul": np.nan,
            "status": "failed",
        }

        is_detection = (
            np.isfinite(values["ts"])
            and values["ts"] >= TS_THRESHOLD
            and np.isfinite(values["energy_flux"])
            and values["energy_flux"] > 0
            and np.isfinite(values["energy_flux_err"])
        )

        if is_detection:
            row["status"] = "detection"
            row["sed_value"] = values["energy_flux"] / delta_log_energy
            row["sed_error"] = values["energy_flux_err"] / delta_log_energy

        elif np.isfinite(values["photon_flux_ul"]) and values["photon_flux_ul"] > 0:
            mean_energy = mean_energy_mev(emin, emax, pl_type, pl_parameters)
            energy_flux_ul = values["photon_flux_ul"] * mean_energy * MEV_TO_ERG

            row["status"] = "upper_limit"
            row["sed_ul"] = energy_flux_ul / delta_log_energy

        rows.append(row)

    print(
        "bin  energy range [MeV]            TS       "
        "E2dN/dE [erg cm^-2 s^-1]         status"
    )
    print("---  --------------------------  -------  -----------------------------  -----------")

    for row in rows:
        energy_range = f"{row['emin_mev']:.3f}-{row['emax_mev']:.3f}"
        ts_text = f"{row['ts']:.3f}" if np.isfinite(row["ts"]) else "--"

        if row["status"] == "detection":
            sed_text = f"{row['sed_value']:.3e} +/- {row['sed_error']:.3e}"
        elif row["status"] == "upper_limit":
            sed_text = f"< {row['sed_ul']:.3e}"
        else:
            sed_text = "--"

        print(
            f"{row['bin']:>3}  {energy_range:<26}  {ts_text:>7}  "
            f"{sed_text:>29}  {row['status']}"
        )

    energy_curve = np.geomspace(100.0, 500000.0, 500)

    sed_pl = (
        energy_curve**2
        * dnde(energy_curve, pl_type, pl_parameters)
        * MEV_TO_ERG
    )

    sed_lp = (
        energy_curve**2
        * dnde(energy_curve, lp_type, lp_parameters)
        * MEV_TO_ERG
    )

    pl_lower, pl_upper = make_butterfly(
        energy_curve,   
        pl_type,
        pl_parameters,
        pl_errors,
    )

    lp_lower, lp_upper = make_butterfly(
        energy_curve,
        lp_type,
        lp_parameters,
        lp_errors,
    )

    fig, ax = plt.subplots(figsize=(6, 4))

    ax.fill_between(
        energy_curve * 1e-3,
        pl_lower,
        pl_upper,
        color="forestgreen",
        alpha=0.35,
        linewidth=0,
        zorder=2,
        # label="PowerLaw: approximate 1σ",
    )

    ax.fill_between(
        energy_curve * 1e-3,
        lp_lower,
        lp_upper,
        color="crimson",
        alpha=0.35,
        linewidth=0,
        zorder=2,
        # label="LogParabola: approximate 1σ",
    )

    ax.plot(
        energy_curve * 1e-3,
        sed_pl,
        color="forestgreen",
        lw=2,
        zorder=3,
        label="PowerLaw",
    )

    ax.plot(
        energy_curve * 1e-3,
        sed_lp,
        color="crimson",
        lw=2,
        ls="--",
        zorder=3,
        label="LogParabola",
    )

    detection_labeled = False
    upper_limit_labeled = False

    for row in rows:
        energy_gev = row["energy_center_mev"] * 1e-3
        emin_gev = row["emin_mev"] * 1e-3
        emax_gev = row["emax_mev"] * 1e-3

        xerr = np.array([
            [energy_gev - emin_gev],
            [emax_gev - energy_gev],
        ])

        if row["status"] == "detection":
            ax.errorbar(
                energy_gev,
                row["sed_value"],
                xerr=xerr,
                yerr=row["sed_error"],
                fmt="o",
                color="tab:blue",
                capsize=3,
                label="Kes 27: TS ≥ 5" if not detection_labeled else None,
            )
            detection_labeled = True

        elif row["status"] == "upper_limit":
            ax.errorbar(
                energy_gev,
                row["sed_ul"],
                xerr=xerr,
                yerr=row["sed_ul"] * 0.35,
                uplims=True,
                fmt="v",
                color="tab:orange",
                capsize=3,
                label="TS < 5: 95% UL" if not upper_limit_labeled else None,
            )
            upper_limit_labeled = True

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Energy [GeV]")
    ax.set_ylabel(r"$E^2 dN/dE$ [erg cm$^{-2}$ s$^{-1}$]")
    # ax.set_title("Kes 27 SED: PowerLaw versus LogParabola")
    # ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="best")

    fig.tight_layout()
    fig.savefig(OUTPUT_PNG, dpi=220, bbox_inches="tight")
    plt.show()

    print(f"\nSaved plot: {OUTPUT_PNG}")


if __name__ == "__main__":
    main()

# %%
