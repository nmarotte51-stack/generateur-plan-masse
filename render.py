"""Rendu du plan-masse -> figure matplotlib (reutilisable par la demo et l'appli)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly


def _xy(poly):
    return list(poly.exterior.coords)


def render_plan(result, parcel_xy, access_pt):
    r = result
    k = r["kpis"]
    xs = [p[0] for p in parcel_xy]
    ys = [p[1] for p in parcel_xy]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    pad = 0.06 * max(w, h) + 2

    # taille de figure proportionnelle au terrain -> pas de deformation ni de
    # cadrage etrange, et la parcelle entiere est toujours visible
    span_x, span_y = w + 2 * pad, h + 2 * pad
    figw = 7.0
    figh = max(3.0, min(9.0, figw * span_y / span_x))
    fig, ax = plt.subplots(figsize=(figw, figh))

    # parcelle (rouge epais)
    ax.add_patch(MplPoly(parcel_xy, fill=False, ec="#c0392b", lw=3, zorder=2))
    # zone constructible (pointilles bleus) dessinee tot
    if r["zone"] is not None:
        ax.add_patch(MplPoly(_xy(r["zone"]), fill=True, fc="#2980b920",
                             ec="#2980b9", lw=1.5, ls="--", zorder=1))
    # voirie interne (tiree depuis l'acces)
    if r.get("voirie") is not None:
        vo = r["voirie"]
        vgeoms = vo.geoms if vo.geom_type == "MultiPolygon" else [vo]
        for gv in vgeoms:
            if not gv.is_empty:
                ax.add_patch(MplPoly(_xy(gv), fc="#d9cbb2", ec="#b8a888", lw=1, zorder=2.5))
    # poche de stationnement (peut etre en plusieurs baies)
    if r["parking"] is not None:
        pk = r["parking"]
        geoms = pk.geoms if pk.geom_type == "MultiPolygon" else [pk]
        for gp in geoms:
            if not gp.is_empty:
                ax.add_patch(MplPoly(_xy(gp), fc="#95a5a655", ec="#555", lw=1, zorder=3))
    for kind, s in r["stalls"]:
        c = "#34495e" if kind == "garage" else "#bdc3c7"
        ax.add_patch(MplPoly(_xy(s), fc=c, ec="white", lw=0.6, zorder=4))
    # batiments (ocre + etiquette)
    for name, g, log in r["buildings"]:
        ax.add_patch(MplPoly(_xy(g), fc="#d35400", ec="#7d3c00", lw=1.2, zorder=5))
        c = g.centroid
        ax.text(c.x, c.y, f"{name}\n{log} lgt", ha="center", va="center",
                color="white", fontsize=7, fontweight="bold", zorder=6)
    # cheminements pietons (serpentent du parking vers chaque coursive)
    for line in r.get("cheminements", []):
        lx, ly = line.xy
        ax.plot(lx, ly, color="#16a085", lw=2.2, ls=(0, (4, 2)), zorder=6.5, alpha=0.9)
    # coursive centrale de chaque batiment
    for corr in r.get("corridors", []):
        lx, ly = corr.xy
        ax.plot(lx, ly, color="#ffffff", lw=1.4, ls=":", zorder=6.6, alpha=0.9)
    # accas
    if access_pt is not None:
        ax.plot(access_pt[0], access_pt[1], "v", color="#e67e22", ms=13, zorder=7)
        ax.annotate("Accas", access_pt, textcoords="offset points", xytext=(0, -14),
                    ha="center", color="#e67e22", fontsize=8, fontweight="bold")

    ax.set_aspect("equal")
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.grid(True, alpha=0.25)
    ax.set_xlabel("metres")
    return fig
