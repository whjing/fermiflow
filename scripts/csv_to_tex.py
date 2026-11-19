#!/usr/bin/env python3
"""Convert spatial-grid --csv output to AASTeX table rows (no header/footer).

Usage: python csv_to_tex.py results.csv results.tex
"""
import argparse
import csv
import re
from pathlib import Path


def escape(value):
    return re.sub(r"([&#%_${}])", r"\\\1", str(value))


def measurement(row, key):
    value = row.get(key, "")
    if not value:
        return "---" if key == "r68" and row["spatial_model"] == "point" else r"\ldots"
    text = f"{float(value):.2f}"
    hi, lo = row.get(key + "_err_hi"), row.get(key + "_err_lo")
    if hi and lo:
        if key == "r68":
            text += rf"^{{+{float(hi):.2f}}}_{{-{float(lo):.2f}}}"
        else:
            text += rf" \pm {float(hi):.2f}"
    return "$" + text + "$"


def convert(input_csv, output_tex):
    with input_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    groups = {}
    for row in rows:
        count = int(row["component_count"])
        groups.setdefault(count, {}).setdefault(row["tag"], []).append(row)
    lines = []
    headings = {0: "Background only", 1: "Single-source", 2: "Two-source", 3: "Three-source"}
    for count, models in sorted(groups.items()):
        if lines:
            lines.append(r"\hline")
        total_rows = sum(len(items) for items in models.values())
        group = rf"\multirow{{{total_rows}}}{{*}}{{{headings.get(count, str(count) + '-source')}}}"
        for model_index, (tag, components) in enumerate(models.items()):
            if model_index:
                lines.append(r"\cline{2-9}")
            lines.append("% " + tag.replace("\n", " "))
            notes = components[0].get("notes", "")
            if notes:
                lines.append("% Notes: " + notes.replace("\n", " "))
            for index, row in enumerate(components):
                model = row["spatial_model"]
                component = ({"gaussian": "Gaussian", "disk": "Disk"}.get(model)
                             or (r"\texttt{" + escape(row["source"]) + "}" if row["source"] else "---"))
                stats = []
                for key in ("nll", "delta_ts", "delta_k", "delta_aic"):
                    value = row.get(key, "")
                    stats.append(("$" + (f"{float(value):.0f}" if key == "delta_k" else f"{float(value):.2f}") + "$")
                                 if value else r"\ldots")
                cells = [group, component, measurement(row, "ra"), measurement(row, "dec"),
                         measurement(row, "r68"), *(stats if index == 0 else [""] * 4)]
                lines.append(" & ".join(cells) + r" \\")
                group = ""
    output_tex.parent.mkdir(parents=True, exist_ok=True)
    output_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {output_tex}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_tex", type=Path)
    args = parser.parse_args()
    convert(args.input_csv, args.output_tex)


if __name__ == "__main__":
    main()
