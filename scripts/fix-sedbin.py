#%%
# %%
#!/usr/bin/env python3
"""Freeze all XML parameters for low-TS sources in one or more SED bins."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
import shlex
import stat

TS_THRESHOLD = 1.0

# 保持这些源原本的 free/fixed 状态。
PROTECTED_SOURCES = {
    "kes27",
    "gll_iem_v07",
    "iso_P8R3_SOURCE_V3_v1",
}

# 每组依次为：(log 文件, 输入 XML 文件)。
# 输出文件自动命名为：xxx_input.xml -> xxx-mod_input.xml
JOBS = [
    # (
    #     Path("../logs/sed_6bin/sed-6bin-01-1992814.log"),
    #     Path("../products_100MeV/bin_01_0p10-0p41GeV/kes27_sed_6bin01_input.xml"),
    # ),
    # (
    #     Path("../logs/sed_6bin/sed-6bin-02-1992815.log"),
    #     Path("../products_100MeV/bin_02_0p41-1p71GeV/kes27_sed_6bin02_input.xml"),
    # ),
    # (
    #     Path("../logs/sed_6bin/sed-6bin-03-1992816.log"),
    #     Path("../products_100MeV/bin_03_1p71-7p07GeV/kes27_sed_6bin03_input.xml"),
    # ),
    # (
    #     Path("../logs/sed_6bin/sed-6bin-04-1992817.log"),
    #     Path("../products_100MeV/bin_04_7p07-29p24GeV/kes27_sed_6bin04_input.xml"),
    # ),
    (
        Path("../logs/sed_6bin/sed-6bin-06-1992819.log"),
        Path("../products_100MeV/bin_05_29p24-120p91GeV/kes27_sed_6bin05_input.xml"),
    ),
    # (
    #     Path("../logs/sed_6bin/sed-6bin-06-1992819.log"),
    #     Path("../products_100MeV/bin_06_120p91-500p00GeV/kes27_sed_6bin06_input.xml"),
    # ),

]

def write_submit_script(model_files):
    """
    Generate one shell script that submits one Slurm SED job per modified XML.
    The generated shell script does not submit anything until you run it.
    """
    script_dir = Path.cwd().resolve()
    run_script = (script_dir / "run_fermitools.py").resolve()
    config_file = (script_dir / "kes27_100MeV.yaml").resolve()

    if not run_script.is_file():
        raise FileNotFoundError(f"run_fermitools.py not found: {run_script}")

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
    sleep 3
    echo "Submitted ${{job_id%%;*}}: ${{tag}} on ${{node}}"
done
"""

    submit_script.write_text(content, encoding="utf-8")
    submit_script.chmod(submit_script.stat().st_mode | stat.S_IXUSR)

    print(f"\\nCreated submission script: {submit_script}")
    print("Submit all modified SED jobs with:")
    print(f"  bash {submit_script}")

    return submit_script

def read_ts_values(log_file):
    """Read source names and TS values from one Fermi fitting log."""
    source_pattern = re.compile(r"\|\s+INFO\s+\|\s+(.+?):\s*$")
    ts_pattern = re.compile(r"\|\s+INFO\s+\|\s+TS value:\s+([-+0-9.eE]+)")

    ts_values = {}
    current_source = None

    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        source_match = source_pattern.search(line)
        if source_match:
            current_source = source_match.group(1).strip()
            continue

        ts_match = ts_pattern.search(line)
        if ts_match and current_source is not None:
            ts_values[current_source] = float(ts_match.group(1))
            current_source = None

    return ts_values


def freeze_source(source):
    """Set every spectrum and spatial parameter of one source to free='0'."""
    changed = 0

    for parameter in source.iter("parameter"):
        if parameter.get("free") != "0":
            parameter.set("free", "0")
            changed += 1

    return changed


def count_free_parameters(root):
    return sum(parameter.get("free") == "1" for parameter in root.iter("parameter"))


def make_output_path(input_model):
    """Convert xxx_input.xml to xxx-mod_input.xml."""
    if not input_model.name.endswith("_input.xml"):
        raise ValueError(f"Unexpected input XML name: {input_model.name}")

    output_name = input_model.name.replace("_input.xml", "-mod_input.xml")
    return input_model.with_name(output_name)


def process_job(job):
    log_file = job[0].expanduser().resolve()
    input_model = job[1].expanduser().resolve()
    output_model = make_output_path(input_model)

    if not log_file.is_file():
        print(f"\nSkip: log file not found: {log_file}")
        return

    if not input_model.is_file():
        print(f"\nSkip: input XML not found: {input_model}")
        return

    ts_values = read_ts_values(log_file)
    if not ts_values:
        print(f"\nSkip: no TS values found in: {log_file}")
        return

    tree = ET.parse(input_model)
    root = tree.getroot()
    xml_sources = {source.get("name"): source for source in root.findall("source")}

    low_ts = []
    high_ts = []
    missing_sources = []

    for source_name, ts_value in sorted(ts_values.items(), key=lambda item: item[1]):
        if source_name in PROTECTED_SOURCES:
            continue

        if ts_value >= TS_THRESHOLD:
            high_ts.append((source_name, ts_value))
            continue

        source = xml_sources.get(source_name)
        if source is None:
            missing_sources.append((source_name, ts_value))
            continue

        changed = freeze_source(source)
        low_ts.append((source_name, ts_value, changed))

    output_model.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output_model, encoding="UTF-8", xml_declaration=True)

    print("\n" + "=" * 78)
    print(f"Log file     : {log_file}")
    print(f"Input model  : {input_model}")
    print(f"Output model : {output_model}")
    print(f"TS threshold : {TS_THRESHOLD:g}")

    # print(f"\nSources fixed: TS < {TS_THRESHOLD:g} ({len(low_ts)})")
    # for source_name, ts_value, changed in low_ts:
    #     print(f"  {source_name:<35} TS = {ts_value:10.5f}   fixed = {changed}")

    # print(f"\nSources retained: TS >= {TS_THRESHOLD:g} ({len(high_ts)})")
    # for source_name, ts_value in high_ts:
    #     print(f"  {source_name:<35} TS = {ts_value:10.5f}")

    if missing_sources:
        print("\nLow-TS sources in log but not in XML:")
        for source_name, ts_value in missing_sources:
            print(f"  {source_name:<35} TS = {ts_value:10.5f}")

    print(f"\nFree parameters in output model: {count_free_parameters(root)}")
    return output_model


def main():
    generated_models = []

    for job in JOBS:
        output_model = process_job(job)

        if output_model is not None:
            generated_models.append(output_model)

    if generated_models:
        write_submit_script(generated_models)
    else:
        print("\nNo modified XML models were generated.")


if __name__ == "__main__":
    main()

# %%
