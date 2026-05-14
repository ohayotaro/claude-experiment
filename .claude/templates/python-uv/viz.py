"""Visualization helpers — minimal core plus user-editable style profiles.

Copied into src/utils/viz.py by /init-experiment regardless of the resolved
runtime (analysis still runs in Python even when the experiment itself is
C++/Rust/Make). After the copy, the file belongs to the project — edit it
freely to suit your taste.

Design philosophy
-----------------
The orchestrator critiques rendered figures via the viz-reviewer agent
(Gemini-backed), so this module deliberately does NOT enforce strong
aesthetic opinions. It provides:

1. Universal data       — colorblind-safe palettes, standard figure widths.
2. Infrastructure       — multi-format save, caption sidecar, font-embedding
                          choice that affects post-render editability and
                          cannot be fixed by Gemini after the fact.
3. Named style profiles — "default" / "publication" / "presentation" as a
                          starting point. Add your own. Override via kwargs.
4. A user preference    — read from CLAUDE.md Zone B `viz_preferences.
                          default_profile`. data-analyst respects it.

Usage
-----

    from utils.viz import apply_style, save_figure, OKABE_ITO

    apply_style()  # uses the project's default profile (Zone B)
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    ax.plot(xs, ys, color=OKABE_ITO["blue"])
    ax.set(xlabel="time (s)", ylabel="response (a.u.)")
    save_figure(fig, "data/results/<run_id>/figures/fig1",
                caption="Mean response over time. Shaded band = 95% CI; n = 24.")

To pick a non-default profile for one call:

    apply_style("presentation")

To override a single rcParam without editing the profile:

    apply_style("publication", **{"font.size": 10})

To define your own profile, edit STYLE_PROFILES below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import matplotlib as mpl
import matplotlib.pyplot as plt

# ----- Palettes (data; not enforcement) -------------------------------------
# Okabe & Ito (2008) — eight distinguishable colors for protan/deutan/tritan.
# https://jfly.uni-koeln.de/color/
OKABE_ITO: dict[str, str] = {
    "black": "#000000",
    "orange": "#E69F00",
    "skyblue": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",   # reserved for highlight / odd-one-out
    "purple": "#CC79A7",
}
OKABE_ITO_CYCLE: list[str] = [
    OKABE_ITO["blue"], OKABE_ITO["vermillion"], OKABE_ITO["green"],
    OKABE_ITO["orange"], OKABE_ITO["skyblue"], OKABE_ITO["purple"],
    OKABE_ITO["yellow"], OKABE_ITO["black"],
]
TABLEAU_CB10: list[str] = [
    "#006BA4", "#FF800E", "#ABABAB", "#595959", "#5F9ED1",
    "#C85200", "#898989", "#A2C8EC", "#FFBC79", "#CFCFCF",
]

# ----- Standard figure widths (inches; data, not enforcement) ---------------
COLUMN_WIDTH = 3.5         # Single-column journal figure
TWO_THIRDS_WIDTH = 5.0     # 1.5-column / Nature half-page
DOUBLE_WIDTH = 7.2         # Double-column journal figure
SLIDE_WIDTH = 6.0          # 16:9 slide column

# ----- Universal infrastructure rcParams ------------------------------------
# Everything here is invisible in the rendered figure but matters for
# post-processing or accessibility. The viz-reviewer agent cannot detect
# these problems from a rendered PNG, so it is appropriate to enforce them
# at template level. They apply regardless of the chosen profile.
_INFRASTRUCTURE_RCPARAMS: dict[str, Any] = {
    "pdf.fonttype": 42,    # TrueType — text editable in vector editors
    "ps.fonttype": 42,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "image.cmap": "viridis",
}

# ----- Style profiles (edit freely after /init-experiment copies this file) -
#
# Each profile is a dict of matplotlib rcParams. Profiles are merged on top
# of _INFRASTRUCTURE_RCPARAMS; later additions to a profile win. Add your
# own profile by appending to STYLE_PROFILES, then either set
# viz_preferences.default_profile in CLAUDE.md Zone B or call
# apply_style("<your-profile>") directly.
STYLE_PROFILES: dict[str, dict[str, Any]] = {
    # Neutral baseline. Okabe-Ito cycle, no top/right spines, otherwise
    # leaves matplotlib defaults alone.
    "default": {
        "axes.prop_cycle": mpl.cycler(color=OKABE_ITO_CYCLE),
        "axes.spines.top": False,
        "axes.spines.right": False,
    },

    # Journal figures: small fonts (figures are reproduced at saved size),
    # serif body, thin lines. Edit fonts/sizes to taste.
    "publication": {
        "axes.prop_cycle": mpl.cycler(color=OKABE_ITO_CYCLE),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.8,
        "axes.titlesize": 9,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 1.2,
        "lines.markersize": 4.0,
        "font.family": "serif",
        "font.serif": [
            "DejaVu Serif", "Liberation Serif", "Nimbus Roman",
            "Times New Roman", "Times", "serif",
        ],
        "font.size": 8.5,
    },

    # Slides / posters: large fonts, sans-serif, thicker lines.
    "presentation": {
        "axes.prop_cycle": mpl.cycler(color=OKABE_ITO_CYCLE),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 1.4,
        "axes.titlesize": 16,
        "axes.labelsize": 14,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "xtick.major.width": 1.4,
        "ytick.major.width": 1.4,
        "xtick.major.size": 5,
        "ytick.major.size": 5,
        "legend.frameon": False,
        "legend.fontsize": 12,
        "lines.linewidth": 2.4,
        "lines.markersize": 7.0,
        "font.family": "sans-serif",
        "font.sans-serif": [
            "DejaVu Sans", "Liberation Sans", "Helvetica", "Arial", "sans-serif",
        ],
        "font.size": 14,
    },
}

DEFAULT_PROFILE_FALLBACK = "default"


# ----- Apply --------------------------------------------------------------
def _read_zone_b_default_profile() -> str | None:
    """Read viz_preferences.default_profile from CLAUDE.md Zone B if present."""
    p = Path("CLAUDE.md")
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    m = re.search(r"<!-- ZONE_B_BEGIN -->(.*?)<!-- ZONE_B_END -->", text, re.DOTALL)
    if not m:
        return None
    zb = m.group(1)
    pref = re.search(r"default_profile\s*:\s*(\S+)", zb)
    return pref.group(1).strip() if pref else None


def apply_style(profile: str | None = None, **overrides: Any) -> str:
    """Apply a named style profile, optionally overriding individual rcParams.

    Resolution order for the profile name:
        1. The ``profile`` argument if given.
        2. ``viz_preferences.default_profile`` from CLAUDE.md Zone B.
        3. ``"default"``.

    Returns the resolved profile name (useful for logging).
    """
    name = profile or _read_zone_b_default_profile() or DEFAULT_PROFILE_FALLBACK
    if name not in STYLE_PROFILES:
        raise KeyError(
            f"Unknown viz style profile: {name!r}. "
            f"Available: {sorted(STYLE_PROFILES)}. "
            f"Add a new entry to STYLE_PROFILES in src/utils/viz.py."
        )
    rc: dict[str, Any] = {}
    rc.update(_INFRASTRUCTURE_RCPARAMS)
    rc.update(STYLE_PROFILES[name])
    rc.update(overrides)
    mpl.rcParams.update(rc)
    return name


# ----- Save ---------------------------------------------------------------
def save_figure(
    fig: plt.Figure,
    path_without_ext: str | Path,
    *,
    formats: Iterable[Literal["pdf", "png", "svg"]] = ("pdf", "png"),
    caption: str | None = None,
    require_caption_or_title: bool = True,
) -> list[Path]:
    """Save a figure consistently across formats and persist its caption.

    Writes a sidecar ``<name>.caption.txt`` if ``caption`` is given, so the
    paper-writer agent can recover figure captions later without re-reading
    the analysis script.

    Raises if the figure has no title and no caption argument and
    ``require_caption_or_title`` is True. This is a research-rigor check,
    not an aesthetic one — silent untitled figures cannot be cited reliably.
    """
    path_without_ext = Path(path_without_ext)
    path_without_ext.parent.mkdir(parents=True, exist_ok=True)

    if require_caption_or_title and caption is None:
        has_title = bool(fig._suptitle and fig._suptitle.get_text().strip())
        if not has_title:
            for ax in fig.get_axes():
                t = ax.get_title()
                if t and t.strip():
                    has_title = True
                    break
        if not has_title:
            raise ValueError(
                f"save_figure({path_without_ext}): figure has no title and no caption "
                "argument. Pass caption='...' or set a title; or pass "
                "require_caption_or_title=False to override."
            )

    written: list[Path] = []
    for fmt in formats:
        out = path_without_ext.with_suffix(f".{fmt}")
        fig.savefig(out, format=fmt)
        written.append(out)

    if caption is not None:
        cap_path = path_without_ext.with_suffix(".caption.txt")
        cap_path.write_text(caption.strip() + "\n", encoding="utf-8")
        written.append(cap_path)

    return written
