#%%
#!/usr/bin/env python3
"""Four G328 TS-map panels with optional DS9 contours, regions and catalogues.

Relative paths are resolved against this script (normally project/scripts).
"""
from pathlib import Path
import re

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS
from matplotlib.lines import Line2D
import matplotlib.patheffects as path_effects
from matplotlib.colors import LinearSegmentedColormap, Normalize
from regions import CircleSkyRegion, EllipseSkyRegion, Regions, SkyRegion
from reproject import reproject_interp

# One font size for titles, source labels, axes, ticks, and colorbar.
FONT_SIZE = 11
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Helvetica', 'Arial', 'Liberation Sans', 'DejaVu Sans'],
    'font.size': FONT_SIZE,
    'axes.titlesize': FONT_SIZE,
    'axes.labelsize': FONT_SIZE,
    'xtick.labelsize': FONT_SIZE,
    'ytick.labelsize': FONT_SIZE,
    'legend.fontsize': FONT_SIZE,
    'mathtext.fontset': 'dejavusans',
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
})

SCRIPT_DIR = Path(__file__).resolve().parent
# The following FITS paths follow your earlier 1GeV filenames. Check that each
# map really uses the background/source exclusions described in its title.
PANELS = [
    ('a', '', '../../g328_pubfermi_bkp/products_1GeV/g328_model_init-1_tsmap-res.fits', 0),
    ('b', '', '../products_1GeV/spatial_grid_less/srcT-N-srcP-P-srcE-D/tsmap-res.fits', 0),
    ('c', '', '../products_1GeV/spatial_grid_more_fixPE/srcT-P/tsmap-res.fits', 0),
    ('d', '', '../products_1GeV/spatial_grid_more_fixPE/srcT-P/tsmap-srcT.fits', 0),
]

# Optional overlays: None or '' means disabled; missing files are skipped.
RADIO_CONTOUR = '../regions/g328_askap.ctr'
RADIO_FRAME = 'fk5'  # Default if the .ctr does not declare fk5/icrs/galactic
FL16Y_REG = '../shared/ROI_g328_model_16yr_carta.reg'
PT_REG = '../products_1GeV/spatial_grid_less/srcT-P-srcP-P-srcE-G/srcT-P-srcP-P-srcE-G.reg'
G328_REG = PT_REG  # Same multi-source file is read once, not drawn twice.
# PSRCAT: psrj,ra_deg,dec_deg. SNRcat: primary_name,ra_deg,dec_deg,
# major_arcmin,minor_arcmin (full diameters); generic name/diameter_arcmin also supported.
PULSAR_CSV = "~/regions/psrcat_v2.9.0-all-sky.csv"
SNR_CSV = "~/regions/SNRcat20261122-SNR-regions.csv"
OUTPUT = '../figures/g328_tsmap_1116.png'

CENTER = SkyCoord(ra=238.885*u.deg, dec=-53.283*u.deg, frame='icrs')
FIELD_DEG = 1.0
PIXEL_DEG = 0.01
LABEL_FL16Y = True
# Shared linear TS scale for every panel.
TS_MIN, TS_MAX = 0.0, 35.0
TS_NORM = Normalize(vmin=TS_MIN, vmax=TS_MAX)
# DS9 BColorMap control points (default contrast/bias):
# https://github.com/SAOImageDS9/SAOImageDS9/blob/master/tksao/colorbar/default.C
DS9_B = LinearSegmentedColormap('ds9_b', {
    'red': [(0, 0, 0), (.25, 0, 0), (.5, 1, 1), (1, 1, 1)],
    'green': [(0, 0, 0), (.5, 0, 0), (.75, 1, 1), (1, 1, 1)],
    'blue': [(0, 0, 0), (.25, 1, 1), (.5, 0, 0), (.75, 0, 0), (1, 1, 1)],
}, N=1024)
OUTLINE_TYPES = (CircleSkyRegion, EllipseSkyRegion)
SOURCE_STYLES = {
    'srcT': (('srct', 'g328'), 'tomato', '--'),
    'srcP': (('srcp', 'pt'), 'deepskyblue', '--'),
    'srcE': (('srce', 'extend'), 'turquoise', '-'),
}


def path_for(value):
    if value is None or not str(value).strip():
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (SCRIPT_DIR / path).resolve()


def optional_file(value):
    path = path_for(value)
    if path is not None and not path.is_file():
        print(f'Skip optional overlay (file not found): {path}')
        return None
    return path


def make_grid():
    npix = int(np.ceil(FIELD_DEG/PIXEL_DEG))
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    wcs.wcs.cunit = ['deg', 'deg']
    wcs.wcs.crval = [CENTER.ra.deg, CENTER.dec.deg]
    wcs.wcs.crpix = [(npix+1)/2, (npix+1)/2]
    # Preserve the requested field size even when FIELD_DEG/PIXEL_DEG is not integral.
    pixel_deg = FIELD_DEG / npix
    wcs.wcs.cdelt = [-pixel_deg, pixel_deg]
    wcs.wcs.radesys = 'ICRS'
    return wcs, (npix, npix)


def project_image(filename, hdu, wcs, shape):
    with fits.open(filename) as hdul:
        image = np.asarray(hdul[hdu].data, dtype=float).squeeze()
        native = WCS(hdul[hdu].header).celestial
    if image.ndim != 2 or not native.has_celestial:
        raise ValueError(f'Need a 2D celestial image: {filename}[{hdu}]')
    data, footprint = reproject_interp((image, native), wcs, shape_out=shape, order='nearest-neighbor')
    data[footprint == 0] = np.nan
    if not np.isfinite(data).any():
        raise ValueError(f'No data in requested field: {filename}')
    covered = np.isfinite(data).mean()
    print(f'{filename.name}: native={image.shape}, output={data.shape}, '
          f'finite coverage={covered:.1%}')
    if covered < 1:
        print('  Uncovered/invalid pixels remain blank; the displayed field is unchanged.')
    return data


def lock_field(ax, shape):
    """Keep a square panel and prevent overlay artists from expanding the view."""
    ax.set_xlim(-0.5, shape[1] - 0.5)
    ax.set_ylim(-0.5, shape[0] - 0.5)
    ax.set_aspect('equal', adjustable='box')
    ax.set_autoscale_on(False)


def read_contours(value):
    """Read DS9 .ctr parenthesized world-coordinate polylines; no FITS needed."""
    path = optional_file(value)
    if path is None:
        return []
    contours, points = [], None
    frame = RADIO_FRAME.lower()
    for raw in path.read_text(errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            # DS9 headers may declare the coordinate frame in a comment.
            if line.startswith('#'):
                match = re.search(r'\b(?:coordsys|coordinate system)\s*[:=]\s*(fk5|icrs|galactic)', line, re.I)
                if match:
                    frame = match[1].lower()
            continue
        if line.lower() in ('fk5', 'icrs', 'galactic'):
            frame = line.lower()
        elif line == '(':
            points = []
        elif line == ')':
            if points and len(points) >= 2:
                a, b = np.asarray(points).T
                try:
                    sky = SkyCoord(l=a*u.deg, b=b*u.deg, frame='galactic') if frame == 'galactic' else SkyCoord(ra=a*u.deg, dec=b*u.deg, frame=frame)
                    contours.append(sky.icrs)
                except ValueError as error:
                    print(f'Skip invalid contour block: {error}')
            points = None
        elif points is not None:
            fields = line.replace(',', ' ').split()
            try:
                a, b = float(fields[0]), float(fields[1])
                if np.isfinite(a) and np.isfinite(b):
                    points.append((a, b))
            except (ValueError, IndexError):
                continue
    if not contours:
        print(f'No valid world-coordinate contour blocks in {path}; skipped')
    return contours


def read_regions(value):
    path = optional_file(value)
    if path is None:
        return []
    try:
        regions = Regions.read(path, format='ds9')
        return [r for r in regions if isinstance(r, SkyRegion)]
    except Exception as error:
        print(f'Skip optional region {path}: {error}')
        return []


def region_label(region):
    return str(region.meta.get('text', '')).strip('{} ')


def catalog_centers(regions):
    entries = {}
    for region in regions:
        center = getattr(region, 'center', None)
        if center is None:
            continue
        center = center.icrs
        key = (round(center.ra.deg, 7), round(center.dec.deg, 7))
        label = region_label(region)
        if key not in entries or (label and not entries[key][1]):
            entries[key] = center, label
    return list(entries.values())


def read_catalog(value):
    """Read PSRCAT, SNRcat or generic name/RA/Dec CSV; sizes are diameters."""
    path = optional_file(value)
    if path is None:
        return []
    table = Table.read(path, format='ascii.csv')
    name_column = next((n for n in ('primary_name', 'psrj', 'name') if n in table.colnames), None)
    if name_column is None or not {'ra_deg', 'dec_deg'}.issubset(table.colnames):
        raise ValueError(f'{path}: need ra_deg, dec_deg and primary_name/psrj/name')

    def number(row, column):
        value = row[column] if column in table.colnames else None
        if value is None or np.ma.is_masked(value) or not str(value).strip():
            return None
        value = float(value)
        return value if np.isfinite(value) and value > 0 else None

    entries = []
    ellipse_count = 0
    for row in table:
        try:
            ra, dec = float(row['ra_deg']), float(row['dec_deg'])
            if not np.isfinite(ra) or not np.isfinite(dec):
                continue
            center = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs')
            name = str(row[name_column]).strip()
            if np.ma.is_masked(row[name_column]) or not name:
                continue
            if name_column == 'psrj':
                name = 'PSR ' + name
            major = number(row, 'major_arcmin') or number(row, 'diameter_arcmin')
            minor = number(row, 'minor_arcmin') or major
            outline = None
            if major is not None:
                if minor is not None and not np.isclose(major, minor):
                    # No position angle is supplied by this SNRcat export.
                    # The displayed ellipse is schematic, with width along RA.
                    outline = EllipseSkyRegion(center, major*u.arcmin, minor*u.arcmin, angle=0*u.deg)
                    ellipse_count += 1
                else:
                    outline = CircleSkyRegion(center, major/2*u.arcmin)
            entries.append((center, name, outline))
        except (ValueError, TypeError) as error:
            print(f'Skip invalid catalogue row in {path.name}: {error}')
    print(f'{path.name}: loaded {len(entries)} objects')
    if ellipse_count:
        print(f'  {ellipse_count} SNR ellipses have no supplied position angle; displayed at 0 deg (schematic).')
    return entries


def source_overlays(regions):
    """Match unlabelled r68 circles to labelled centre markers; old names work too."""
    overlays = []
    for name, (aliases, color, linestyle) in SOURCE_STYLES.items():
        centers = [r.center.icrs for r in regions if hasattr(r, 'center') and region_label(r).lower().split(' ')[0] in aliases]
        if not centers:
            continue
        unique = {(round(c.ra.deg, 7), round(c.dec.deg, 7)): c for c in centers}
        for center in unique.values():
            outlines = [r for r in regions if isinstance(r, OUTLINE_TYPES) and r.center.separation(center) < 1*u.arcsec]
            overlays.append((name, center, outlines, color, linestyle))
    return overlays


def mark(ax, wcs, shape, center, label, color, marker, size=6):
    x, y = wcs.world_to_pixel(center.icrs)
    if not (-.5 <= x < shape[1]-.5 and -.5 <= y < shape[0]-.5):
        return
    ax.plot(x, y, marker=marker, ls='none', ms=size, mfc='none', mec=color, zorder=5)
    if label:
        ax.annotate(label, (x, y), xytext=(5, 5), textcoords='offset points', color=color, fontsize=FONT_SIZE, clip_on=True, zorder=6)


def draw_outline(ax, wcs, region, color, linestyle='-'):
    ax.add_artist(region.to_pixel(wcs).as_artist(facecolor='none', edgecolor=color, linestyle=linestyle, linewidth=1.1, clip_on=True, zorder=4))


def main():
    # Only base-map FITS files are required. Optional overlays never block plotting.
    missing = [str(path_for(filename)) for _, _, filename, _ in PANELS
               if path_for(filename) is None or not path_for(filename).is_file()]
    if missing:
        raise SystemExit('Missing panel FITS (edit PANELS):\n' + '\n'.join(missing))
    wcs, shape = make_grid()
    contours = read_contours(RADIO_CONTOUR)
    fl16y = catalog_centers(read_regions(FL16Y_REG))
    pulsars, snrs = read_catalog(PULSAR_CSV), read_catalog(SNR_CSV)
    all_regions, seen = [], set()
    for value in (PT_REG, G328_REG):
        path = path_for(value)
        if path is not None and path not in seen:
            seen.add(path)
            all_regions.extend(read_regions(path))
    overlays = source_overlays(all_regions)
    fig = plt.figure(figsize=(10, 9.4))
    grid = fig.add_gridspec(2, 3, width_ratios=[1, 1, .035],
                           left=.09, right=.94, bottom=.08, top=.96,
                           wspace=.09, hspace=.10)
    axes = np.array([[fig.add_subplot(grid[row, col], projection=wcs)
                      for col in range(2)] for row in range(2)])
    colorbar_ax = fig.add_subplot(grid[:, 2])
    for ax, (key, title, filename, hdu) in zip(axes.flat, PANELS):
        data = project_image(path_for(filename), hdu, wcs, shape)
        image = ax.imshow(data, origin='lower', interpolation='nearest', cmap=DS9_B, norm=TS_NORM)
        lock_field(ax, shape)
        for sky in contours:
            ax.plot(sky.ra.deg, sky.dec.deg, transform=ax.get_transform('icrs'), color='gold', lw=.9, zorder=3)
        for center, name in fl16y:
            mark(ax, wcs, shape, center, name if LABEL_FL16Y else '', 'white', '+')
        for center, name, _ in pulsars:
            mark(ax, wcs, shape, center, name, 'lime', 'D', 5)
        for center, name, outline in snrs:
            if outline is not None:
                draw_outline(ax, wcs, outline, 'cyan')
            mark(ax, wcs, shape, center, name, 'cyan', 'o', 4)
        for name, center, outlines, color, linestyle in overlays:
            for outline in outlines:
                draw_outline(ax, wcs, outline, color, linestyle)
            mark(ax, wcs, shape, center, name, color, '+', 8)
        lock_field(ax, shape)
        ax.text(0.03, 0.03, f'({key})', transform=ax.transAxes,
                ha='left', va='bottom', fontsize=FONT_SIZE, color='white',
                path_effects=[path_effects.withStroke(linewidth=2, foreground='black')],
                zorder=10)
        ax.coords[0].set_axislabel('R.A. (J2000)')
        ax.coords[1].set_axislabel('Dec. (J2000)')
        ax.coords[0].set_major_formatter('hh:mm')
        ax.coords[1].set_major_formatter('dd:mm')
        for coord in ax.coords:
            coord.set_ticklabel(size=FONT_SIZE)
        row, col = np.argwhere(axes == ax)[0]
        if row == 0:
            ax.coords[0].set_ticklabel_visible(False)
            ax.coords[0].set_axislabel('')
        if col == 1:
            ax.coords[1].set_ticklabel_visible(False)
            ax.coords[1].set_axislabel('')
    colorbar = fig.colorbar(image, cax=colorbar_ax, label='TS', ticks=np.arange(0, 36, 5))
    colorbar.ax.tick_params(labelsize=FONT_SIZE)
    colorbar.ax.yaxis.label.set_size(FONT_SIZE)
    handles = []
    if contours:
        handles.append(Line2D([], [], color='gold', label='G328 radio contours'))
    for entries, color, marker, label in [(fl16y, 'gray', '+', 'FL16Y'), (pulsars, 'lime', 'D', 'Pulsar'), (snrs, 'cyan', 'o', 'SNR')]:
        if entries:
            handles.append(Line2D([], [], color=color, marker=marker, mfc='none', ls='none', label=label))
    for name in SOURCE_STYLES:
        if any(r[0] == name for r in overlays):
            _, color, linestyle = SOURCE_STYLES[name]
            handles.append(Line2D([], [], color=color, marker='+', ls=linestyle, label=name))
    output = path_for(OUTPUT)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reapply after every overlay and colorbar has been added.
    for ax in axes.flat:
        lock_field(ax, shape)
    print(f'All panels: center=({CENTER.ra.deg:.6f}, {CENTER.dec.deg:.6f}), '
          f'field={FIELD_DEG:g} x {FIELD_DEG:g} deg (TAN projection plane)')
    fig.savefig(output, dpi=300, bbox_inches='tight')
    print(f'Saved: {output}')
    plt.show()


if __name__ == '__main__':
    main()

# %%
