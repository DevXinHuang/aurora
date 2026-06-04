from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


DOWNLOADS = Path("/Users/xin/Downloads")
OUT_BASE = DOWNLOADS / "Daniel_Huang_PICASO_Workflow_Flowchart"


COLORS = {
    "ink": "#2b2f33",
    "dark": "#62696d",
    "mid": "#a8afb2",
    "light": "#edf1f1",
    "paper": "#f7f8f7",
    "blue": "#c8dce4",
    "green": "#dbe8df",
    "rose": "#efd4cc",
    "sand": "#eee6d6",
    "line": "#4b5257",
    "accent": "#2f7ea3",
}


def wrap_lines(lines, width):
    wrapped = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=width, break_long_words=False))
    return "\n".join(wrapped)


def add_box(
    ax,
    x,
    y,
    w,
    h,
    title,
    lines,
    *,
    face="#edf1f1",
    header="#62696d",
    edge="#4b5257",
    title_color="white",
    body_color="#27323a",
    title_size=11,
    body_size=8.6,
    radius=0.018,
    wrap=24,
    lw=1.2,
):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=face,
        zorder=2,
    )
    ax.add_patch(box)
    header_h = min(0.038, h * 0.22)
    ax.add_patch(
        Rectangle(
            (x + 0.006, y + h - header_h - 0.006),
            w - 0.012,
            header_h,
            facecolor=header,
            edgecolor=edge,
            linewidth=0.5,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2,
        y + h - header_h / 2 - 0.006,
        title,
        ha="center",
        va="center",
        fontsize=title_size,
        color=title_color,
        fontweight="bold",
        zorder=4,
    )
    ax.text(
        x + 0.018,
        y + h - header_h - 0.022,
        wrap_lines(lines, wrap),
        ha="left",
        va="top",
        fontsize=body_size,
        color=body_color,
        linespacing=1.16,
        zorder=4,
    )
    return box


def add_small_box(
    ax,
    x,
    y,
    w,
    h,
    text,
    *,
    face="#a8afb2",
    edge="#4b5257",
    color="white",
    fontsize=7.6,
    wrap=18,
):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.004,rounding_size=0.015",
        linewidth=1.0,
        edgecolor=edge,
        facecolor=face,
        zorder=4,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h / 2,
        wrap_lines([text], wrap),
        ha="center",
        va="center",
        fontsize=fontsize,
        color=color,
        linespacing=1.08,
        zorder=5,
    )
    return box


def arrow(ax, start, end, *, rad=0.0, color="#4b5257", lw=1.4, ms=12):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=ms,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
        zorder=1,
        shrinkA=4,
        shrinkB=4,
    )
    ax.add_patch(patch)
    return patch


def add_bar(ax, x, y, w, h, text, *, color="#62696d", fontsize=12):
    ax.add_patch(Rectangle((x, y), w, h, facecolor=color, edgecolor=COLORS["line"], linewidth=1.1, zorder=2))
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="white",
        fontweight="bold",
        zorder=3,
    )


def main():
    fig, ax = plt.subplots(figsize=(20, 14), dpi=220)
    fig.patch.set_facecolor(COLORS["paper"])
    ax.set_facecolor(COLORS["paper"])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.965,
        "PICASO Sub-Neptune Planet-Typing Workflow",
        ha="center",
        va="center",
        fontsize=27,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        0.5,
        0.932,
        "ReflectX-style schematic based on Daniel Huang's AABC proposal and the timestep/RoadRunner PICASO workflow",
        ha="center",
        va="center",
        fontsize=12.2,
        color="#56616a",
    )

    # Top panel: computation flow.
    ax.text(
        0.055,
        0.892,
        "DIAGRAM OF HOW MODELS ARE COMPUTED",
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=COLORS["ink"],
    )

    add_box(
        ax,
        0.055,
        0.635,
        0.205,
        0.225,
        "INPUTS",
        [
            "Science question: can cloudy, volatile-rich sub-Neptunes near the radius valley look terrestrial in reflected light?",
            "Proposal grid: FGK hosts, HZ separations, enrichment up to ~1000x solar, cloud levers, and mission-relevant wavelength windows.",
            "Current timestep inputs: PICASO reference data plus SLGRID pressure-temperature and cloud files.",
        ],
        face=COLORS["blue"],
        header=COLORS["dark"],
        wrap=31,
        body_size=7.7,
    )

    add_box(
        ax,
        0.300,
        0.710,
        0.168,
        0.130,
        "MODEL SETUP",
        [
            "SystemParams builds each case: Teff, logg, Rp, a_AU, phase_deg, star T/R.",
            "PICASO opacity connection sets the wavelength range.",
        ],
        face="#dfe8eb",
        header=COLORS["dark"],
        wrap=25,
        body_size=7.2,
    )

    add_box(
        ax,
        0.300,
        0.565,
        0.168,
        0.112,
        "ATMOSPHERE",
        [
            "resolve_slgrid_files selects paired PT and cloud files.",
            "Cloud-column names are normalized before case.clouds(...).",
        ],
        face="#dfe8eb",
        header=COLORS["dark"],
        wrap=25,
        body_size=7.0,
    )

    add_box(
        ax,
        0.515,
        0.710,
        0.195,
        0.130,
        "REFLECTED-LIGHT STEP",
        [
            "case.star + case.gravity + case.atmosphere + case.clouds.",
            "case.phase_angle(phase_deg) then spectrum(..., calculation='reflected').",
        ],
        face=COLORS["green"],
        header="#6f777a",
        wrap=30,
        body_size=7.2,
    )

    add_box(
        ax,
        0.515,
        0.565,
        0.195,
        0.122,
        "THERMAL / ANALOG STEP",
        [
            "PICASO thermal uses phase=0, or hybrid workflow injects EGP g31 IRflux.",
            "Earth benchmark spectra and abiotic terrestrial analogs form the comparison set.",
        ],
        face=COLORS["sand"],
        header="#6f777a",
        wrap=30,
        body_size=7.0,
    )

    add_box(
        ax,
        0.750,
        0.615,
        0.185,
        0.190,
        "POST-PROCESS",
        [
            "Convert wavenumber to wavelength.",
            "Use fp/fs or albedo to recover absolute reflected planet flux.",
            "Interpolate onto LAM_GRID; integrate Roman CGI bands and proposed HWO windows.",
            "Compute f_reflect and spectral similarity metrics.",
        ],
        face=COLORS["rose"],
        header="#6f777a",
        wrap=27,
        body_size=7.25,
    )

    add_box(
        ax,
        0.380,
        0.480,
        0.300,
        0.066,
        "FINAL OUTPUT",
        [
            "Sub-Neptune spectral library, confusion-region maps, diagnostic wavelength windows, and planet-typing guidance.",
        ],
        face="#cdd8dc",
        header=COLORS["dark"],
        wrap=58,
        body_size=7.8,
    )

    add_small_box(
        ax,
        0.065,
        0.575,
        0.185,
        0.042,
        "Implementation path: timestep/2_9_2026 -> phase-60 hybrid notebook -> migrated picaso4 workflow",
        face="#8b9498",
        fontsize=7.4,
        wrap=35,
    )

    arrow(ax, (0.260, 0.755), (0.300, 0.775))
    arrow(ax, (0.260, 0.690), (0.300, 0.622), rad=-0.08)
    arrow(ax, (0.468, 0.775), (0.515, 0.775))
    arrow(ax, (0.468, 0.622), (0.515, 0.624))
    arrow(ax, (0.710, 0.775), (0.750, 0.735))
    arrow(ax, (0.710, 0.624), (0.750, 0.672))
    arrow(ax, (0.842, 0.615), (0.655, 0.546), rad=0.12)
    arrow(ax, (0.612, 0.565), (0.606, 0.546), rad=-0.10, lw=1.1, ms=9)

    # Bottom panel: model grid structure.
    ax.text(
        0.055,
        0.445,
        "DIAGRAM OF GRID STRUCTURE",
        ha="left",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=COLORS["ink"],
    )

    gx, gy, gw, gh = 0.065, 0.030, 0.870, 0.390
    ax.add_patch(Rectangle((gx, gy), gw, gh, fill=False, edgecolor=COLORS["line"], linewidth=1.3, zorder=1))
    add_bar(ax, gx + 0.006, gy + gh - 0.034, gw - 0.012, 0.026, "MODEL", color=COLORS["dark"], fontsize=12.5)

    row_specs = [
        ("HOST STAR", 0.355, ["FGK host bins", "stellar spectra", "HZ separation / isolation"]),
        ("PLANET", 0.264, ["radius-valley target", "sub-Neptune envelope", "Teff, logg, Rp, a_AU"]),
        ("ATMOSPHERE + CLOUDS", 0.173, ["metallicity / MMW", "SLGRID PT profile", "cloud top + opacity", "fsed / cloud fraction"]),
        ("OBSERVATION + METRICS", 0.082, ["phase geometry", "0.3-1.0 um current grid; 0.3-2.5 um proposal", "Roman CGI / HWO windows", "band depth + slopes", "CIA / continuum", "noise similarity"]),
    ]

    for label, y0, _items in row_specs:
        add_bar(ax, gx + 0.025, y0, gw - 0.050, 0.023, label, color="#6f777a", fontsize=10.8)

    def grid_item(x, y, w, text, face="#aeb5b8", wrap=18):
        return add_small_box(ax, x, y, w, 0.040, text, face=face, color="white", fontsize=7.0, wrap=wrap)

    x0 = gx + 0.045
    gap = 0.012
    host_w = (gw - 0.110 - 2 * gap) / 3
    for i, text in enumerate(row_specs[0][2]):
        grid_item(x0 + i * (host_w + gap), 0.305, host_w, text, face="#9fa7ab", wrap=20)

    planet_w = (gw - 0.110 - 2 * gap) / 3
    for i, text in enumerate(row_specs[1][2]):
        grid_item(x0 + i * (planet_w + gap), 0.214, planet_w, text, face="#a7acae", wrap=21)

    atm_w = (gw - 0.110 - 3 * gap) / 4
    for i, text in enumerate(row_specs[2][2]):
        grid_item(x0 + i * (atm_w + gap), 0.123, atm_w, text, face="#a2ada7", wrap=18)

    obs_items = row_specs[3][2]
    obs_w = (gw - 0.110 - 5 * gap) / 6
    for i, text in enumerate(obs_items):
        grid_item(x0 + i * (obs_w + gap), 0.032, obs_w, text, face="#b5a9a5", wrap=16)

    # Braces / connectors between rows.
    for x in [x0 + host_w / 2, x0 + host_w + gap + host_w / 2, x0 + 2 * (host_w + gap) + host_w / 2]:
        arrow(ax, (x, 0.305), (x, 0.288), lw=0.8, ms=7)
    for x in [x0 + planet_w / 2, x0 + planet_w + gap + planet_w / 2, x0 + 2 * (planet_w + gap) + planet_w / 2]:
        arrow(ax, (x, 0.214), (x, 0.197), lw=0.8, ms=7)
    for x in [x0 + 1.5 * (atm_w + gap), x0 + 2.5 * (atm_w + gap)]:
        arrow(ax, (x, 0.123), (x, 0.106), lw=0.8, ms=7)

    ax.text(
        0.5,
        0.010,
        "Key code references: roadrunner.config -> roadrunner.system -> roadrunner.runner / workflows.hybrid_reflected_picaso_thermal_egp -> roadrunner.bands -> output CSVs",
        ha="center",
        va="center",
        fontsize=8.5,
        color="#5a646b",
    )

    for ext in ("png", "pdf", "svg"):
        fig.savefig(f"{OUT_BASE}.{ext}", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    print(f"{OUT_BASE}.png")
    print(f"{OUT_BASE}.pdf")
    print(f"{OUT_BASE}.svg")


if __name__ == "__main__":
    main()
