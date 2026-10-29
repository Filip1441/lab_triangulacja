"""Generates the cross-section of the double-sided demo plate (flat side / smooth asymmetric wave side).

Coordinates in mm: x across the plate, y toward the wave side (+) / flat side (-); rotation axis at origin.
Writes profile.svg (clean, for CAD import: outline + axis circle) and profile_preview.png (annotated).
"""
import numpy as np

WIDTH = 100.0
HALF_T = 4.5        # flat face at y=-HALF_T, wave mean plane at y=+HALF_T (both HALF_T from the axis)
AMP = 6.0           # wave +-AMP around its mean plane
LAMBDA = 70.0
H2, PHASE2 = 0.2, 1.0
AXIS_D = 3.0
N_SEG = 40

xs = np.linspace(-WIDTH / 2, WIDTH / 2, 4001)


def _raw(x):
    u = 2 * np.pi * x / LAMBDA
    return np.sin(u) + H2 * np.sin(2 * u + PHASE2)


_g = _raw(xs)
_mid, _half = (_g.max() + _g.min()) / 2, (_g.max() - _g.min()) / 2


def wave_y(x):
    return HALF_T + AMP * (_raw(np.asarray(x, float)) - _mid) / _half


def bezier_path(nodes_x):
    """Cubic Bezier through wave nodes (Hermite slopes from the analytic curve), SVG y flipped (up = wave side)."""
    h = 1e-3
    y = wave_y(nodes_x)
    d = (wave_y(nodes_x + h) - wave_y(nodes_x - h)) / (2 * h)
    segs = []
    for i in range(len(nodes_x) - 1):
        dx = nodes_x[i + 1] - nodes_x[i]
        c1 = (nodes_x[i] + dx / 3, y[i] + d[i] * dx / 3)
        c2 = (nodes_x[i + 1] - dx / 3, y[i + 1] - d[i + 1] * dx / 3)
        segs.append(f"C {c1[0]:.4f} {-c1[1]:.4f} {c2[0]:.4f} {-c2[1]:.4f} {nodes_x[i+1]:.4f} {-y[i+1]:.4f}")
    return y, segs


def build_svg():
    nodes = np.linspace(-WIDTH / 2, WIDTH / 2, N_SEG + 1)
    y, segs = bezier_path(nodes)
    x0, x1 = -WIDTH / 2, WIDTH / 2
    d = (f"M {x0} {HALF_T} L {x0} {-y[0]:.4f} " + " ".join(segs) +
         f" L {x1} {HALF_T} Z")
    r = AXIS_D / 2
    vb = (-60, -45, 120, 90)
    k = 96 / 25.4  # CAD importers (Fusion) read SVG user units as px at 96 dpi: scale so 1 mm stays 1 mm
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{vb[2]*k:.4f}" height="{vb[3]*k:.4f}" viewBox="{vb[0]*k:.4f} {vb[1]*k:.4f} {vb[2]*k:.4f} {vb[3]*k:.4f}">
  <!-- Drawing is 1:1 in mm (group scaled by 96/25.4 for px import). Up = wave side, down = flat side. Origin = rotation axis. -->
  <g transform="scale({k:.7f})">
    <path id="profil" d="{d}" fill="none" stroke="#000" stroke-width="0.1"/>
    <circle id="os_obrotu" cx="0" cy="0" r="{r}" fill="none" stroke="#d00" stroke-width="0.1"/>
  </g>
</svg>
"""


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    open("profile.svg", "w").write(build_svg())
    yy = wave_y(xs)
    slope = np.degrees(np.arctan(np.abs(np.gradient(yy, xs)).max()))
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.fill_between(xs, -HALF_T, yy, color="#cfcfcf", ec="k", lw=1.2)
    ax.axhline(HALF_T, color="#888", ls="--", lw=0.8)
    ax.axhline(-HALF_T, color="#888", ls="--", lw=0.8)
    ax.plot(0, 0, "o", mfc="none", mec="#d00", ms=14)
    ax.axvline(0, color="#d00", lw=0.8, ls="-.", ymin=0.1, ymax=0.9)
    ax.axhline(0, color="#d00", lw=0.8, ls="-.")
    ax.text(2, 1.0, "oś obrotu", color="#d00")
    ax.text(0, HALF_T + AMP + 3, f"strona fali ({2*AMP:.0f} mm p-p, maks. nachylenie {slope:.0f}°)", ha="center")
    ax.text(0, -HALF_T - 3.5, "strona płaska", ha="center")
    ax.text(51, HALF_T + 1, f"średnia płaszczyzna fali\n(= {HALF_T:.0f} mm od osi)", fontsize=8, va="bottom")
    ax.set_aspect("equal")
    ax.set_xlim(-60, 80)
    ax.set_ylim(-12, 20)
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_title(f"Przekrój płytki demo, szerokość 100 mm, odległość płaska-średnia fali {2*HALF_T:.0f} mm")
    fig.tight_layout()
    fig.savefig("profile_preview.png", dpi=130)
    print("slope max", slope, "min y", yy.min(), "max y", yy.max(), "wave y(0)", wave_y(0.0))
