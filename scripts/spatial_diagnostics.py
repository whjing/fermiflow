"""Compare fitted source centres and extensions across spatial hypotheses."""
import csv
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def geometry(source):
    spatial = source.find('spatialModel')
    parameters = {p.get('name'): p for p in spatial.findall('parameter')}
    def value(name):
        p = parameters[name]
        return float(p.get('value')) * float(p.get('scale', '1'))
    ra, dec = value('RA'), value('DEC')
    radius = None
    if spatial.get('type') == 'RadialGaussian':
        radius = value('Sigma') * math.sqrt(-2 * math.log(.32))
    elif spatial.get('type') == 'RadialDisk':
        radius = value('Radius') * math.sqrt(.68)
    if not all(math.isfinite(v) for v in (ra, dec)) or not -90 <= dec <= 90:
        raise ValueError('Invalid source centre')
    if radius is not None and (not math.isfinite(radius) or radius < 0):
        raise ValueError('Invalid source extension')
    return ra, dec, radius


def collect_positions(rows, names, read_errors):
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    records = []
    for row in rows:
        if not any(row.get(name) in ('point', 'gaussian', 'disk') for name in names):
            continue
        final = Path(row.get('spatial_final_model') or Path(row['output_dir']) / (row['tag'] + '_spatial_final.xml'))
        if not final.is_file():
            candidates = sorted(final.parent.glob(final.stem + '_*.xml'), key=lambda p: p.stat().st_mtime)
            if candidates:
                final = candidates[-1]
        if not final.is_file():
            print(f"Skip position comparison {row['tag']}: no final spatial XML")
            continue
        try:
            initial = {s.get('name'): s for s in ET.parse(row['input_model']).getroot().findall('source')}
            fitted = {s.get('name'): s for s in ET.parse(final).getroot().findall('source')}
        except (OSError, ET.ParseError) as error:
            print(f"Skip position comparison {row['tag']}: {error}")
            continue
        for name in names:
            model = row.get(name)
            if model not in ('point', 'gaussian', 'disk'):
                continue
            try:
                ira, idec, ir = geometry(initial[name])
                ra, dec, radius = geometry(fitted[name])
            except (KeyError, TypeError, AttributeError, ValueError) as error:
                print(f"Skip position comparison {row['tag']}/{name}: {error}")
                continue
            origin = SkyCoord(ira * u.deg, idec * u.deg, frame='icrs')
            center = SkyCoord(ra * u.deg, dec * u.deg, frame='icrs')
            dx, dy = origin.spherical_offsets_to(center)
            errors = read_errors(row.get('output_dir'), name, model)
            failed = bool(errors.get('failed'))
            matched = all(math.isclose(v, errors.get(k, math.nan), rel_tol=0, abs_tol=1/3600)
                          for k, v in (('ra', ra), ('dec', dec)))
            status = 'failed_or_out_of_bounds' if failed else ('available' if matched else 'uncertainties_unavailable_or_mismatched')
            def error_value(key):
                value = errors.get(key, math.nan)
                return value if not failed and matched and math.isfinite(value) and value > 0 else ''
            records.append(dict(
                tag=row['tag'], source=name, spatial_model=model,
                input_ra=ira, input_dec=idec, fitted_ra=ra, fitted_dec=dec,
                delta_ra_cosdec_arcmin=dx.to_value(u.arcmin), delta_dec_arcmin=dy.to_value(u.arcmin),
                separation_arcmin=origin.separation(center).to_value(u.arcmin),
                input_r68_deg=ir if ir is not None else '', fitted_r68_deg=radius if radius is not None else '',
                delta_r68_deg=radius-ir if radius is not None and ir is not None else '',
                ra_err_deg=error_value('ra_err'), dec_err_deg=error_value('dec_err'),
                r68_err_hi_deg=error_value('ext_err_hi'), r68_err_lo_deg=error_value('ext_err_lo'),
                status=status, input_xml=row['input_model'], fitted_xml=str(final),
            ))
    return records


def plot_positions(rows, names, output, csv_output, read_errors, coordinates="absolute"):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    if coordinates not in ("absolute", "offset"):
        raise ValueError("plot.position_coordinates must be absolute or offset")
    records = collect_positions(rows, names, read_errors)
    if not records:
        print('No fitted positions available for the position comparison.')
        return
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    tags = list(dict.fromkeys(r['tag'] for r in records))
    colors = {tag: plt.get_cmap('tab20')(i % 20) for i, tag in enumerate(tags)}
    numbers = {tag: i+1 for i, tag in enumerate(tags)}
    markers = {'point': 'o', 'gaussian': '^', 'disk': 's'}
    present = [name for name in names if any(r['source'] == name for r in records)]
    figure, axes = plt.subplots(len(present), 2, figsize=(15, 4.8*len(present)+3), squeeze=False)
    for index, name in enumerate(present):
        position, radii = axes[index]
        subset = [r for r in records if r['source'] == name]
        for y, r in enumerate(subset):
            color, marker = colors[r['tag']], markers[r['spatial_model']]
            failed = r['status'] == 'failed_or_out_of_bounds'
            if coordinates == "absolute":
                dx, dy = r['fitted_ra'], r['fitted_dec']
                xerr = r['ra_err_deg'] if r['ra_err_deg'] != '' else None
                yerr = r['dec_err_deg'] if r['dec_err_deg'] != '' else None
                position.scatter([r['input_ra']], [r['input_dec']], marker='+', color='black', s=100, zorder=6)
            else:
                dx, dy = r['delta_ra_cosdec_arcmin'], r['delta_dec_arcmin']
                xerr = r['ra_err_deg'] * math.cos(math.radians(r['fitted_dec'])) * 60 if r['ra_err_deg'] != '' else None
                yerr = r['dec_err_deg'] * 60 if r['dec_err_deg'] != '' else None
            position.errorbar(dx, dy, xerr=xerr, yerr=yerr, fmt=marker, color=color, capsize=2,
                              markersize=7, markerfacecolor='none' if failed else color)
            position.annotate(str(numbers[r['tag']]), (dx, dy), xytext=(5, 4), textcoords='offset points', fontsize=7)
            if failed:
                position.scatter([dx], [dy], marker='x', color='darkorange', s=65, zorder=5)
            if r['input_r68_deg'] != '' and r['fitted_r68_deg'] != '':
                old, new = r['input_r68_deg']*60, r['fitted_r68_deg']*60
                radii.plot([old, new], [y, y], color=color, alpha=.6)
                radii.scatter([old], [y], marker='o', facecolors='none', edgecolors='gray', s=50)
                hi, lo = r['r68_err_hi_deg'], r['r68_err_lo_deg']
                err = [[lo*60], [hi*60]] if hi != '' and lo != '' else None
                radii.errorbar([new], [y], xerr=err, fmt=marker, color=color, capsize=2,
                               markerfacecolor='none' if failed else color)
                if failed:
                    radii.scatter([new], [y], marker='x', color='darkorange', s=65, zorder=5)
            else:
                radii.text(.02, y, 'Point: no extension', transform=radii.get_yaxis_transform(), fontsize=8, color=color)
        if coordinates == "absolute":
            position.set(xlabel='R.A. (J2000) [deg]', ylabel='Decl. (J2000) [deg]',
                         title=f'{name}: fitted centres; input marked +')
            position.ticklabel_format(axis='both', style='plain', useOffset=False)
            position.invert_xaxis()
            position.set_aspect(1 / max(abs(math.cos(math.radians(subset[0]['input_dec']))), 1e-6), adjustable='datalim')
        else:
            position.axhline(0, color='gray', lw=.7)
            position.axvline(0, color='gray', lw=.7)
            position.scatter([0], [0], marker='+', color='black', s=100, zorder=6)
            position.set(xlabel=r'$\Delta\mathrm{RA}\cos(\mathrm{Dec})$ [arcmin; east]',
                         ylabel=r'$\Delta\mathrm{Dec}$ [arcmin; north]', title=f'{name}: fitted minus own input centre')
            position.set_aspect('equal', adjustable='datalim')
            position.invert_xaxis()
        position.grid(alpha=.25)
        radii.set_yticks(range(len(subset)), [f"{numbers[r['tag']]:02d} {r['spatial_model']}" for r in subset], fontsize=7)
        radii.set_ylim(len(subset)-.5, -.5)
        radii.set(xlabel=r'Extension $r_{68}$ [arcmin]', title=f'{name}: input (open gray) vs fitted (colored)')
        radii.grid(axis='x', alpha=.25)
    handles = [Line2D([], [], marker='o', linestyle='', color=colors[tag], label=f'{numbers[tag]:02d} {tag}') for tag in tags]
    handles.append(Line2D([], [], marker='x', linestyle='', color='darkorange', label='Failed / out of bounds; no reliable errors'))
    figure.legend(handles=handles, loc='lower center', ncol=2, fontsize=8, frameon=False)
    figure.suptitle('Spatial-model stability: positions and extensions', fontsize=14)
    figure.tight_layout(rect=(0, .17, 1, .97))
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=200, bbox_inches='tight')
    plt.close(figure)
    print(f'Saved position comparison: {output}')
    print(f'Saved position measurements: {csv_output}')
