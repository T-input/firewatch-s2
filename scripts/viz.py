"""
viz.py — Vizualizacija

Sve slike su u istom CRS-u (UTM 34N) kao i granica, crtaj poligon izravno
preko rastera bez reprojekcije. Kadrovi imaju isti dpi/figsize za izradu GIFa.
"""
from __future__ import annotations

from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import imageio.v2 as imageio

import config as cfg

# Fiksne dimenzije kadra (da svi GIF frameovi budu isti)
FIG_W, FIG_H, DPI = 8.0, 8.4, 120

BORDER_COLOR = "#00e5ff"

# Colormap za NBR: crveno (opozareno) -> zuto -> zeleno (vegetacija)
NBR_CMAP = LinearSegmentedColormap.from_list(
    "nbr", ["#7a0403", "#d43d1a", "#f5b820", "#f7f7c8", "#7fbf3f", "#1a7a3a"]
)


def _extent(bbox):
    return (bbox.min_x, bbox.max_x, bbox.min_y, bbox.max_y)


def _base_ax():
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    ax = fig.add_axes([0.0, 0.0, 1.0, 0.94])
    return fig, ax


def _draw_title(fig, text, sub=None):
    fig.text(0.02, 0.975, text, fontsize=16, fontweight="bold",
             va="top", ha="left", color="black")
    if sub:
        fig.text(0.98, 0.975, sub, fontsize=11, va="top", ha="right",
                 color="#555555")


# --------------------------------------------------------------------------
def render_rgb(rgba: np.ndarray, gdf, bbox, title: str, out_path,
               subtitle: str | None = None):
    """Nacrtaj RGBA sliku + granicu + naslov, spremi PNG. Vrati putanju."""
    fig, ax = _base_ax()
    ax.imshow(rgba, extent=_extent(bbox), origin="upper")
    gdf.boundary.plot(ax=ax, edgecolor=BORDER_COLOR, linewidth=1.8)
    ax.set_xlim(bbox.min_x, bbox.max_x)
    ax.set_ylim(bbox.min_y, bbox.max_y)
    ax.set_axis_off()
    _draw_title(fig, title, subtitle)
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


def render_nbr(nbr: np.ndarray, mask: np.ndarray, gdf, bbox, title: str,
               out_path, subtitle: str | None = None):
    """Nacrtaj NBR indeks s colormapom + colorbar + granica. Vrati putanju."""
    data = np.ma.masked_where(mask < 0.5, nbr)
    fig, ax = _base_ax()
    im = ax.imshow(data, extent=_extent(bbox), origin="upper",
                   cmap=NBR_CMAP, vmin=-0.5, vmax=0.8)
    gdf.boundary.plot(ax=ax, edgecolor="black", linewidth=1.4)
    ax.set_xlim(bbox.min_x, bbox.max_x)
    ax.set_ylim(bbox.min_y, bbox.max_y)
    ax.set_axis_off()
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.01)
    cbar.set_label("NBR  (nisko = opozareno,  visoko = vegetacija)", fontsize=9)
    _draw_title(fig, title, subtitle)
    fig.savefig(out_path, dpi=DPI)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------
def build_gif(frame_paths: List[str], out_path, fps: float = 2.0):
    """Spoji PNG kadrove u animirani GIF."""
    frames = []
    ref_shape = None
    for p in frame_paths:
        img = imageio.imread(p)
        if ref_shape is None:
            ref_shape = img.shape
        elif img.shape != ref_shape:
            print(f"  ! preskacem kadar razlicite velicine: {p}")
            continue
        frames.append(img)
    if not frames:
        raise RuntimeError("Nema kadrova za GIF.")
    imageio.mimsave(out_path, frames, duration=1.0 / fps, loop=0)
    return out_path
