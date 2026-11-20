#!/usr/bin/env python3
"""Generate fixed-spatial PL/LP combinations and compare completed gtlike fits."""
import argparse
import csv
import itertools
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from spatial_grid import (load_grid_config, resolve_path, file_label,
                          resolve_slurm_config, write_gtlike_sbatch,
                          write_submit_script, load_model_policy,
                          apply_model_policy_to_sources)

def parameter(spectrum, name):
    p = spectrum.find(f"parameter[@name='{name}']")
    return float(p.get('value')) * float(p.get('scale', '1'))


def make_model(input_model, output_model, selections):
    input_model, output_model = input_model.resolve(), output_model.resolve()
    if input_model == output_model or not output_model.name.endswith('_input.xml'):
        raise ValueError('Write a separate *_input.xml; keep the fitted template unchanged')
    tree = ET.parse(input_model)
    root = tree.getroot()
    for selection in selections:
        name, model = selection.rsplit('=', 1)
        model = model.lower()
        if model not in ('pl', 'lp', 'logparabola'):
            raise ValueError(f'Unsupported spectrum: {model}')
        source = root.find(f"source[@name='{name}']")
        if source is None:
            raise ValueError(f'Source missing: {name}')
        old = source.find('spectrum')
        kind = old.get('type')
        if kind == 'PowerLaw':
            norm, pivot, gamma = parameter(old, 'Prefactor'), parameter(old, 'Scale'), -parameter(old, 'Index')
            scale = float(old.find("parameter[@name='Prefactor']").get('scale', '1'))
        elif kind == 'LogParabola':
            norm, pivot, gamma = parameter(old, 'norm'), parameter(old, 'Eb'), parameter(old, 'alpha')
            scale = float(old.find("parameter[@name='norm']").get('scale', '1'))
        else:
            raise ValueError(f'{name}: only PowerLaw/LogParabola conversion supported, got {kind}')
        if not all(math.isfinite(v) for v in (scale, pivot, norm, gamma)) or scale <= 0 or pivot <= 0 or norm < 0 or not 0 <= gamma <= 10:
            raise ValueError(f'{name}: invalid initial spectral parameters')
        pl = model == 'pl'
        new = ET.Element('spectrum', type='PowerLaw' if pl else 'LogParabola', normPar='Prefactor' if pl else 'norm')
        specs = [('Prefactor' if pl else 'norm',norm/scale,scale,0,max(1e6,10*norm/scale),1),
                 ('Index' if pl else 'alpha',gamma,-1 if pl else 1,0,10,1)]
        if not pl:
            specs.append(('beta',0.,1,-5,10,1))
        specs.append(('Scale' if pl else 'Eb',pivot,1,min(10,pivot),max(500000,pivot),0))
        for key,value,sc,lo,hi,free in specs:
            ET.SubElement(new,'parameter',name=key,value=str(value),scale=str(sc),min=str(lo),max=str(hi),free=str(free))
        source.remove(old)
        source.insert(0,new)
    for source in root.findall('source'):
        spatial=source.find('spatialModel')
        if spatial is not None:
            for p in spatial.findall('parameter'):
                p.set('free','0')
    output_model.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(tree,space='  ')
    tree.write(output_model,encoding='UTF-8',xml_declaration=True)
    print(f'Saved {output_model}; beta starts at zero; spatial parameters fixed')


def settings(path):
    config = load_grid_config(path)
    base = config["base"]
    root = resolve_path(base["output_root"], path.parent)
    return config, base, root


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate(path):
    config, base, output = settings(path)
    template = resolve_path(base["input_model"], path.parent)
    project = resolve_path(base["project_config"], path.parent)
    if not project.is_file():
        raise FileNotFoundError(project)
    sources = config.get("sources") or []
    names = [item["name"] for item in sources]
    if not names or len(set(names)) != len(names):
        raise ValueError("Provide a nonempty sources list with unique names")
    choices = []
    aliases = {"pl": "PL", "powerlaw": "PL", "lp": "LP", "logparabola": "LP"}
    available = {s.get("name") for s in ET.parse(template).getroot().findall("source")}
    tags = set()
    for item in sources:
        if item["name"] not in available:
            raise ValueError(f"Source missing: {item['name']}")
        models = item.get("models")
        if not isinstance(models, list) or not models:
            raise ValueError("Each source needs a nonempty models list")
        options = list(dict.fromkeys(aliases[str(m).lower()] for m in models))
        choices.append(options)
    planned = []
    for values in itertools.product(*choices):
        tag = "-".join(f"{file_label(n)}-{m}" for n, m in zip(names, values))
        if tag in tags:
            raise ValueError(f"Duplicate sanitized tag: {tag}")
        tags.add(tag)
        model = output / tag / f"{tag}_input.xml"
        if model.resolve() == template:
            raise ValueError("Output would overwrite input template")
        planned.append((tag, values, model))
    policy_path = resolve_path(base.get("model_policy"), path.parent)
    policy = load_model_policy(policy_path) if policy_path else None
    slurm_values = dict(config.get("slurm") or {})
    slurm_values.setdefault("sbatch_dir", str(output / "sbatch"))
    slurm_values.setdefault("log_dir", str(output / "logs"))
    slurm = resolve_slurm_config(slurm_values, path.parent, output, "spectral_grid")
    rows, jobs = [], []
    for index, (tag, values, model) in enumerate(planned):
        make_model(template, model, [f"{n}={m.lower()}" for n,m in zip(names, values)])
        if policy:
            tree = ET.parse(model)
            apply_model_policy_to_sources(tree.getroot(), policy)
            # Spatial parameters stay fixed even if the supplied policy frees them.
            for p in tree.findall("./source/spatialModel/parameter"):
                p.set("free", "0")
            tree.write(model, encoding="UTF-8", xml_declaration=True)
        job = slurm["sbatch_dir"] / f"{tag}_like.sbatch"
        log = slurm["log_dir"] / f"{tag}_like.log"
        slurm["index"] = index
        write_gtlike_sbatch(job, tag, project, model, log, slurm)
        jobs.append(job)
        rows.append(dict(tag=tag, input_model=str(model),
                         final_model=str(model.with_name(f"{tag}_minuit.xml")),
                         log=str(log), sbatch=str(job), **dict(zip(names, values))))
    write_csv(output / "spectral_grid_manifest.csv", rows)
    write_submit_script(slurm["sbatch_dir"] / "submit_like.sh", jobs)
    print(f"Generated {len(rows)} combinations; submit manually: bash {slurm['sbatch_dir'] / 'submit_like.sh'}")


def fit_result(row):
    log, model = Path(row["log"]), Path(row["final_model"])
    if not log.is_file() or not model.is_file():
        raise ValueError("log or final XML missing")
    latest = nll = None
    text = log.read_text(errors="replace")
    for line in text.splitlines():
        match = re.search(r"-log\(Likelihood\):\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)", line)
        if match:
            latest = float(match[1])
        if "[DONE] gtlike (MINUIT) finished" in line:
            nll = latest
    if nll is None or not math.isfinite(nll) or "Model fitting workflow completed." not in text:
        raise ValueError("MINUIT/workflow not completed")
    if "Traceback (most recent call last)" in text:
        raise ValueError("log contains a traceback")
    k = sum(p.get("free") == "1" for p in ET.parse(model).getroot().iter("parameter"))
    warnings = "; ".join(dict.fromkeys(line.strip() for line in text.splitlines()
                                     if "WARNING" in line or "return code" in line))
    return dict(row, neg_log_likelihood=nll, k=k, notes=warnings)


def compare(path, reference=None, csv_path=None):
    config, base, output = settings(path)
    with (output / "spectral_grid_manifest.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    completed = []
    for row in rows:
        try:
            completed.append(fit_result(row))
        except (ValueError, ET.ParseError, OSError) as error:
            print(f"Skip {row['tag']}: {error}")
    if not completed:
        raise ValueError("No completed fits")
    reference = reference or (config.get("comparison") or {}).get("reference")
    ref = next((r for r in completed if r["tag"] == reference), None) if reference else min(completed, key=lambda r: r["neg_log_likelihood"] + r["k"])
    if ref is None:
        raise ValueError(f"Reference is not completed: {reference}")
    completed.sort(key=lambda r: r["neg_log_likelihood"] + r["k"])
    for rank, row in enumerate(completed, 1):
        row["rank"] = rank
        row["delta_ts"] = 2 * (ref["neg_log_likelihood"] - row["neg_log_likelihood"])
        row["delta_k"] = row["k"] - ref["k"]
        row["delta_aic"] = 2 * row["delta_k"] - row["delta_ts"]
        row["reference"] = ref["tag"]
        print(f"{rank:3} {row['tag']:45} -logL={row['neg_log_likelihood']:.2f} k={row['k']} deltaTS={row['delta_ts']:.2f} deltaAIC={row['delta_aic']:.2f}")
    write_csv(csv_path or output / "spectral_comparison.csv", completed)
    # Compare one source at a time, holding all other spectral choices equal.
    pairs = []
    names = [s["name"] for s in config["sources"]]
    for pl in completed:
        for lp in completed:
            changed = [n for n in names if pl[n] != lp[n]]
            if len(changed) == 1 and pl[changed[0]] == "PL" and lp[changed[0]] == "LP":
                ts = 2 * (pl["neg_log_likelihood"] - lp["neg_log_likelihood"])
                dk = lp["k"] - pl["k"]
                pairs.append(dict(source=changed[0], pl=pl["tag"], lp=lp["tag"],
                                  ts_curve=ts, delta_k=dk, delta_aic=2*dk-ts))
    if pairs:
        write_csv(output / "spectral_curvature.csv", pairs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--compare-likelihood", action="store_true")
    parser.add_argument("--reference")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    path = args.config.expanduser().resolve()
    if args.compare_likelihood:
        compare(path, args.reference, args.csv)
    elif args.reference or args.csv:
        parser.error("--reference/--csv require --compare-likelihood")
    else:
        generate(path)


if __name__ == "__main__":
    main()
