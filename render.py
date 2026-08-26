"""
Rendu "plan-masse de presentation" -> figure matplotlib.

Code couleur professionnel :
  - espaces verts / jardins ...... vert doux
  - enrobe carrossable (voirie + poche) ... gris anthracite
  - mail pietonnier + antennes ... sable / ocre
  - batiments .................... terre cuite + OMBRE PORTEE (effet maquette)
  - garages / places ............. anthracite fonce / gris clair
  - limite parcellaire ........... rouge epais + COTES en metres sur le perimetre
"""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly

C_VERT   = "#bcd6a7"
C_ENROBE = "#3b3f45"
C_MAIL   = "#d8c39a"
C_BATI   = "#c85a3a"
C_BATI_E = "#7a3115"
C_OMBRE  = "#00000030"
C_GARAGE = "#2c3e50"
C_PLACE  = "#d5dbe0"
C_PARC   = "#b0281c"
C_ZONE   = "#4b7fa6"


def _polys(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    return []


def _fill(ax, geom, **kw):
    for g in _polys(geom):
        if not g.is_empty:
            ax.add_patch(MplPoly(list(g.exterior.coords), **kw))


def render_plan(result, parcel_xy, access_pt):
    r = result
    k = r["kpis"]
    xs = [p[0] for p in parcel_xy]
    ys = [p[1] for p in parcel_xy]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    pad = 0.08 * max(w, h) + 4
    figw = 8.0
    figh = max(3.5, min(10.0, figw * (h + 2 * pad) / (w + 2 * pad)))
    fig, ax = plt.subplots(figsize=(figw, figh))

    # 1. fond vert (jardins / espaces verts) sur toute la parcelle
    ax.add_patch(MplPoly(parcel_xy, fc=C_VERT, ec="none", zorder=1))
    # 1b. zone constructible (repere faible)
    _fill(ax, r.get("zone"), fill=False, ec=C_ZONE, lw=1.2, ls=(0, (6, 4)), alpha=0.7, zorder=1.5)

    # 2. enrobe carrossable : voirie + poche de stationnement
    _fill(ax, r.get("voirie"), fc=C_ENROBE, ec="none", zorder=2)
    _fill(ax, r.get("parking"), fc=C_ENROBE, ec="#2a2d31", lw=1, zorder=2.1)

    # 3. mail pietonnier (sable) + antennes orthogonales (sable clair)
    _fill(ax, r.get("mail"), fc=C_MAIL, ec="#b8a271", lw=1, zorder=2.3)
    for seg in r.get("cheminements", []):
        band = seg.buffer(0.8, cap_style=2)
        _fill(ax, band, fc=C_MAIL, ec="none", alpha=0.95, zorder=2.3)

    # 4. emplacements dans la poche
    for kind, s in r.get("stalls", []):
        c = C_GARAGE if kind == "garage" else C_PLACE
        ax.add_patch(MplPoly(list(s.exterior.coords), fc=c, ec="white", lw=0.5, zorder=3))

    # 5. batiments avec OMBRE PORTEE
    off = 0.02 * max(w, h) + 0.4
    for name, g, log, ent in r["buildings"]:
        shadow = [(x + off, y - off) for (x, y) in g.exterior.coords]
        ax.add_patch(MplPoly(shadow, fc=C_OMBRE, ec="none", zorder=4))
    for name, g, log, ent in r["buildings"]:
        ax.add_patch(MplPoly(list(g.exterior.coords), fc=C_BATI, ec=C_BATI_E, lw=1.4, zorder=5))
        c = g.centroid
        ax.text(c.x, c.y, f"{name}\n{log} lgt", ha="center", va="center",
                color="white", fontsize=6.5, fontweight="bold", zorder=6)
    # coursive centrale
    for corr in r.get("corridors", []):
        lx, ly = corr.xy
        ax.plot(lx, ly, color="white", lw=1.2, ls=":", zorder=6.1, alpha=0.9)

    # 6. acces
    if access_pt is not None:
        ax.plot(access_pt[0], access_pt[1], "v", color="#e67e22", ms=15,
                markeredgecolor="white", zorder=7)
        ax.annotate("ACCES", access_pt, textcoords="offset points", xytext=(0, -16),
                    ha="center", color="#d35400", fontsize=8, fontweight="bold", zorder=7)

    # 7. limite parcellaire (rouge) + COTES sur chaque segment
    ax.add_patch(MplPoly(parcel_xy, fill=False, ec=C_PARC, lw=3, zorder=8))
    cxp, cyp = sum(xs) / len(xs), sum(ys) / len(ys)
    pts = list(parcel_xy)
    for i in range(len(pts)):
        (x1, y1) = pts[i]
        (x2, y2) = pts[(i + 1) % len(pts)]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1.5:
            continue
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if ang > 90 or ang < -90:
            ang += 180
        nx, ny = -(y2 - y1) / L, (x2 - x1) / L          # normale
        if (mx + nx - cxp) ** 2 + (my + ny - cyp) ** 2 < (mx - cxp) ** 2 + (my - cyp) ** 2:
            nx, ny = -nx, -ny                            # pousse la cote vers l'exterieur
        offd = 0.02 * max(w, h) + 1.2
        ax.text(mx + nx * offd, my + ny * offd, f"{L:.1f} m", ha="center", va="center",
                color=C_PARC, fontsize=6.5, rotation=ang, rotation_mode="anchor", zorder=9)

    ax.set_aspect("equal")
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.axis("off")
    fig.tight_layout()
    return fig
