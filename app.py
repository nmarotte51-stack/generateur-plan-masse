# -*- coding: utf-8 -*-
"""
GENERATEUR PLAN MASSE - CARRE DE L'HABITAT
Application autonome (un seul fichier) : moteur generatif + rendu + interface.

>>> Un seul fichier a deployer. Les anciens engine.py / paths.py / render.py ne
    sont plus utilises : remplace uniquement app.py sur GitHub.

Chaine metier : Acces -> Voirie courte -> Poche groupee -> MAIL central ->
produits standard (KAIA/NAIA/DAIA/TAIA) en RANGEES se faisant face. VRD minimise.
Echelle : cote de reference (2 points + longueur reelle), verifiable a l'ecran.
"""
import math
import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly, Circle
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, box, Point, LineString, MultiPoint
from shapely.affinity import rotate
from shapely.ops import unary_union, nearest_points, voronoi_diagram
from streamlit_image_coordinates import streamlit_image_coordinates

# ==================================================================
#  DONNEES PRODUITS
# ==================================================================
BUILDINGS = {
    "KAIA": {"w": 14.20, "h": 15.80, "log": 4},
    "NAIA": {"w": 15.80, "h": 15.80, "log": 4},
    "DAIA": {"w":  8.10, "h": 14.20, "log": 2},
    "TAIA": {"w":  8.10, "h": 21.14, "log": 3},
}
PLACE  = {"w": 2.50, "d": 5.00}
GARAGE = {"w": 2.78, "d": 5.50}
ALLEE  = 5.50
DEFAULTS = {"retrait_sep": 3.0, "retrait_voie": 5.0, "dist_inter": 6.0,
            "ces_max": 1.0, "espaces_verts_min": 0.0, "voirie_larg": 5.0,
            "mail_larg": 3.0, "enabled": list(BUILDINGS.keys())}

# ==================================================================
#  MOTEUR - OUTILS GEOMETRIQUES
# ==================================================================
def _largest(g):
    if g is None or g.is_empty:
        return None
    if g.geom_type == "Polygon":
        return g
    if g.geom_type == "MultiPolygon":
        return max(g.geoms, key=lambda x: x.area)
    if g.geom_type == "GeometryCollection":
        polys = [x for x in g.geoms if x.geom_type == "Polygon"]
        return max(polys, key=lambda x: x.area) if polys else None
    return None


def longest_edge_angle(poly):
    xy = list(poly.exterior.coords)
    bl, ba = 0.0, 0.0
    for i in range(len(xy) - 1):
        (x1, y1), (x2, y2) = xy[i], xy[i + 1]
        L = math.hypot(x2 - x1, y2 - y1)
        if L > bl:
            bl, ba = L, math.degrees(math.atan2(y2 - y1, x2 - x1))
    return ba


def _road_edge(parcel_xy, access_pt):
    xy = list(Polygon(parcel_xy).exterior.coords)
    ap = Point(access_pt)
    best, bd = None, 1e18
    for i in range(len(xy) - 1):
        seg = LineString([xy[i], xy[i + 1]])
        if seg.distance(ap) < bd:
            bd, best = seg.distance(ap), seg
    return best


def constructible_zone(parcel_xy, r_sep, r_voie=None, access_pt=None):
    poly = Polygon(parcel_xy)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zc = _largest(poly.buffer(-r_sep, join_style=2, mitre_limit=5.0))
    if zc is None:
        return None
    if r_voie and access_pt is not None and r_voie > r_sep:
        zc = _largest(zc.difference(_road_edge(parcel_xy, access_pt).buffer(r_voie)))
    return zc


def parking_pocket(zone, parcel, access_pt, n_log, ang):
    if n_log <= 0 or zone is None:
        return None, []
    gd, pd = GARAGE["d"], PLACE["d"]
    depth = gd + ALLEE + pd
    col_w = max(GARAGE["w"], PLACE["w"])
    cx, cy = parcel.centroid.x, parcel.centroid.y
    zr = rotate(zone, -ang, origin=(cx, cy))
    pr = rotate(parcel, -ang, origin=(cx, cy))
    ax = rotate(Point(access_pt), -ang, origin=(cx, cy))
    pminx, pminy, pmaxx, pmaxy = pr.bounds
    if abs(ax.y - pminy) <= abs(ax.y - pmaxy):
        y0, d = pminy, +1.0
    else:
        y0, d = pmaxy - depth, -1.0
    stalls, rects, placed, bays = [], [], 0, 0
    while placed < n_log and bays < 8:
        bays += 1
        if y0 < pminy - 1e-6 or y0 + depth > pmaxy + 1e-6:
            break
        if d > 0:
            py, gy = y0, y0 + pd + ALLEE
        else:
            py, gy = y0 + depth - pd, y0
        cols, x = [], pminx
        while x + col_w <= pmaxx + 1e-6:
            pl = box(x, py, x + PLACE["w"], py + pd)
            gr = box(x, gy, x + GARAGE["w"], gy + gd)
            if pr.contains(pl.buffer(-1e-6)) and zr.contains(gr.buffer(-1e-6)):
                cols.append((x, gr, pl))
            x += col_w
        if cols:
            need = n_log - placed
            cols.sort(key=lambda c: abs((c[0] + col_w / 2) - ax.x))
            take = sorted(cols[:need], key=lambda c: c[0])
            for _, g, pc in take:
                stalls += [("garage", g), ("place", pc)]
                placed += 1
            rects.append(box(min(c[0] for c in take), y0,
                             max(c[0] for c in take) + col_w, y0 + depth))
        y0 += depth * d
    if not stalls:
        return None, []
    bay = unary_union(rects).intersection(pr)
    bay = rotate(bay, ang, origin=(cx, cy))
    stalls = [(k, rotate(s, ang, origin=(cx, cy))) for k, s in stalls]
    return bay, stalls


def central_axis(poly):
    r = poly.minimum_rotated_rectangle
    p = list(r.exterior.coords)[:4]
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if math.dist(p[0], p[1]) >= math.dist(p[1], p[2]):
        a, b = mid(p[1], p[2]), mid(p[3], p[0])
    else:
        a, b = mid(p[0], p[1]), mid(p[2], p[3])
    return LineString([a, b])


def _orient(b):
    o = [(b["w"], b["h"]), (b["h"], b["w"])]
    return o if o[0] != o[1] else [o[0]]


def _place_row(zone_r, pocket_r, placed_all, side, near_y, x_lo, x_hi,
               types, gap, zy0, zy1, step=1.0):
    placed, x = [], x_lo
    while x < x_hi:
        best = None
        for name in types:
            b = BUILDINGS[name]
            for (wx, wy) in _orient(b):
                y0, y1 = (near_y, near_y + wy) if side > 0 else (near_y - wy, near_y)
                if y0 < zy0 - 1e-6 or y1 > zy1 + 1e-6 or x + wx > x_hi + 1e-6:
                    continue
                foot = box(x, y0, x + wx, y1)
                if not zone_r.contains(foot.buffer(-0.05)):
                    continue
                if pocket_r is not None and foot.distance(pocket_r) < gap:
                    continue
                if any(foot.distance(f) < gap - 1e-6 for f in placed_all):
                    continue
                best = (name, foot, b["log"], (x + wx / 2, near_y), wx)
                break
            if best:
                break
        if best:
            placed.append(best)
            placed_all.append(best[1])
            x += best[4] + gap
        else:
            x += step
    return placed


def _layout(parcel, zone, access_pt, ang, p):
    origin = zone.centroid.coords[0]
    R = lambda g: rotate(g, -ang, origin=origin)
    Rb = lambda g: rotate(g, ang, origin=origin)
    zone_r = R(zone)
    zx0, zy0, zx1, zy1 = zone_r.bounds
    gap, mail_w = p["dist_inter"], p["mail_larg"]
    walk = max(1.2, (gap - mail_w) / 2 + 0.5)
    types = sorted(p["enabled"], key=lambda t: -BUILDINGS[t]["log"])
    ces_cap = p["ces_max"] * parcel.area if p["ces_max"] < 1.0 else float("inf")

    def cap_ces(bl):
        bl = sorted(bl, key=lambda b: -b[1].area)
        kept, s = [], 0.0
        for b in bl:
            if s + b[1].area <= ces_cap + 1e-6:
                kept.append(b); s += b[1].area
        return kept

    def do_rows(pocket_r, my):
        nu, nd = my + mail_w / 2 + walk, my - mail_w / 2 - walk
        pa = []
        up = _place_row(zone_r, pocket_r, pa, +1, nu, zx0, zx1, types, gap, zy0, zy1)
        dn = _place_row(zone_r, pocket_r, pa, -1, nd, zx0, zx1, types, gap, zy0, zy1)
        return up + dn

    mail_y = (zy0 + zy1) / 2.0
    rows = cap_ces(do_rows(None, mail_y))
    L = sum(b[2] for b in rows)
    bay, stalls = None, []
    for _ in range(6):
        bay, stalls = parking_pocket(zone, parcel, access_pt, max(L, 1), ang)
        pocket_r = R(bay) if bay is not None else None
        r2 = cap_ces(do_rows(pocket_r, mail_y))
        L2 = sum(b[2] for b in r2)
        if L2 == L:
            rows = r2
            break
        rows, L = r2, L2
    if not rows:
        return {"buildings": [], "L": 0, "parking": bay, "stalls": stalls,
                "voirie": None, "mail": None, "cheminements": [], "corridors": []}

    xs = [b[3][0] for b in rows]
    x_lo, x_hi = min(xs), max(xs)
    if bay is not None:
        x_lo = min(x_lo, R(bay).centroid.x)
    mail_r = box(x_lo, mail_y - mail_w / 2, x_hi, mail_y + mail_w / 2).intersection(zone_r)
    mail_world = Rb(mail_r) if (mail_r is not None and not mail_r.is_empty) else None

    stubs = []
    for b in rows:
        ex, ey = b[3]
        side = 1 if ey > mail_y else -1
        edge_y = mail_y + (mail_w / 2) * side
        seg = LineString([(ex, edge_y), (ex, ey)])
        if seg.length > 0.01:
            stubs.append(Rb(seg))

    bw = [(b[0], Rb(b[1]), b[2], Rb(Point(b[3])).coords[0]) for b in rows]
    corridors = [central_axis(x[1]) for x in bw]
    voirie = None
    if bay is not None:
        voirie = LineString([access_pt, (bay.centroid.x, bay.centroid.y)]).buffer(
            p["voirie_larg"] / 2, cap_style=2).intersection(parcel)
        voirie = voirie if not voirie.is_empty else None
    return {"buildings": bw, "L": sum(b[2] for b in bw), "parking": bay,
            "stalls": stalls, "voirie": voirie, "mail": mail_world,
            "cheminements": stubs, "corridors": corridors}


def compute_feasibility(parcel_xy, access_pt, params):
    p = dict(DEFAULTS); p.update(params or {})
    parcel = Polygon(parcel_xy)
    if access_pt is None:
        access_pt = list(parcel.centroid.coords)[0]
    zone = constructible_zone(parcel_xy, p["retrait_sep"], p["retrait_voie"], access_pt)
    res = {"parcel": parcel, "zone": zone, "access": access_pt, "params": p,
           "buildings": [], "parking": None, "stalls": [], "voirie": None,
           "mail": None, "cheminements": [], "corridors": [], "espaces_verts_all": None,
           "angle": 0.0, "message": None}
    if zone is None or zone.area < 5:
        res["message"] = "Zone constructible vide (retraits trop forts / terrain trop petit)."
        res["kpis"] = _kpis(res); return res
    if not p["enabled"]:
        res["message"] = "Aucun produit autorise."
        res["kpis"] = _kpis(res); return res
    base = longest_edge_angle(zone)
    best, bang = None, base
    for a in (base, base + 90.0):
        lay = _layout(parcel, zone, access_pt, a, p)
        if best is None or lay["L"] > best["L"]:
            best, bang = lay, a
    res.update(buildings=best["buildings"], parking=best["parking"], stalls=best["stalls"],
               voirie=best["voirie"], mail=best["mail"], cheminements=best["cheminements"],
               corridors=best["corridors"], angle=bang)
    if not best["buildings"]:
        res["message"] = "Terrain trop petit ou contraintes trop fortes (aucun batiment plaçable)."
    occ = [b[1] for b in best["buildings"]]
    for key in ("parking", "voirie", "mail"):
        if best[key] is not None:
            occ.append(best[key])
    occ += [s.buffer(0.6) for s in best["cheminements"]]
    verts = parcel.difference(unary_union(occ)) if occ else parcel
    res["espaces_verts_all"] = verts if (verts and not verts.is_empty) else None

    # parcellaire privatif : cellules de Voronoi autour de chaque batiment,
    # clippees a la parcelle -> limites = haies (aspect lotissement)
    plots = []
    if len(best["buildings"]) >= 2:
        try:
            cents = MultiPoint([b[1].centroid for b in best["buildings"]])
            vor = voronoi_diagram(cents, envelope=parcel.buffer(2))
            for cell in vor.geoms:
                c = cell.intersection(parcel)
                if not c.is_empty and c.area > 1:
                    plots.append(c)
        except Exception:
            plots = []
    res["plots"] = plots

    res["kpis"] = _kpis(res)
    return res


def _kpis(r):
    p = r.get("params", {})
    sp = r["parcel"].area
    sb = sum(b[1].area for b in r["buildings"])
    nl = sum(b[2] for b in r["buildings"])
    ng = sum(1 for k, _ in r["stalls"] if k == "garage")
    npl = sum(1 for k, _ in r["stalls"] if k == "place")
    spo = r["parking"].area if r.get("parking") else 0.0
    sv = r["voirie"].area if r.get("voirie") else 0.0
    sm = r["mail"].area if r.get("mail") else 0.0
    sver = r["espaces_verts_all"].area if r.get("espaces_verts_all") else max(0.0, sp - sb - spo - sv - sm)
    ml = sv / max(p.get("voirie_larg", 5.0), 0.1) if sv else 0.0
    st_ok = min(ng, npl)
    emp = sb / sp * 100 if sp else 0
    ev = sver / sp * 100 if sp else 0
    return {"surface_parcelle_m2": round(sp, 1), "surface_batie_m2": round(sb, 1),
            "surface_espaces_verts_m2": round(sver, 1),
            "surface_poche_stationnement_m2": round(spo, 1),
            "surface_voirie_m2": round(sv, 1), "surface_mail_m2": round(sm, 1),
            "ml_voirie": round(ml, 1), "nb_logements": nl, "nb_places": npl,
            "nb_garages": ng, "emprise_au_sol_pct": round(emp, 1),
            "espaces_verts_pct": round(ev, 1),
            "ratio_vrd_par_logement_m2": round((spo + sv + sm) / nl, 1) if nl else 0,
            "ces_respecte": emp <= p.get("ces_max", 1.0) * 100 + 0.1,
            "espaces_verts_respecte": ev >= p.get("espaces_verts_min", 0.0) * 100 - 0.1,
            "stationnement_suffisant": st_ok >= nl,
            "logements_non_stationnes": max(0, nl - st_ok)}


# ==================================================================
#  RENDU "PLAN-MASSE DE PRESENTATION"
# ==================================================================
C_LAWN, C_ENROBE, C_MAIL = "#c2d6a0", "#41464d", "#d9c49b"
C_ROOF, C_ROOFLINE = "#b95c37", "#6f3418"
C_GARAGE, C_PLACE = "#2c3e50", "#dfe4e8"
C_TREE, C_TREE2 = "#4f8043", "#79ab5f"
C_PARC, C_ZONE = "#b0281c", "#6a97b8"


def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if g.geom_type == "MultiPolygon":
        return list(g.geoms)
    if g.geom_type == "GeometryCollection":
        return [x for x in g.geoms if x.geom_type == "Polygon" and not x.is_empty]
    return []


def _fill(ax, geom, **kw):
    for g in _polys(geom):
        ax.add_patch(MplPoly(list(g.exterior.coords), **kw))


def _roof(ax, poly):
    axis = central_axis(poly)
    p1 = axis.interpolate(0.30, normalized=True).coords[0]
    p2 = axis.interpolate(0.70, normalized=True).coords[0]
    ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=C_ROOFLINE, lw=1.3, zorder=5.3)
    for cx, cy in list(poly.exterior.coords)[:4]:
        end = p1 if math.dist((cx, cy), p1) < math.dist((cx, cy), p2) else p2
        ax.plot([cx, end[0]], [cy, end[1]], color=C_ROOFLINE, lw=0.7, zorder=5.3)


def _tree(ax, x, y, r=1.9):
    ax.add_patch(Circle((x + 0.5, y - 0.5), r, fc="#0000001f", ec="none", zorder=3.3))
    ax.add_patch(Circle((x, y), r, fc=C_TREE2, ec=C_TREE, lw=1.1, zorder=3.5))
    ax.add_patch(Circle((x, y), r * 0.45, fc=C_TREE, ec="none", zorder=3.6))


def render_plan(result, parcel_xy, access_pt):
    r = result
    xs = [p[0] for p in parcel_xy]
    ys = [p[1] for p in parcel_xy]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    cxp, cyp = sum(xs) / len(xs), sum(ys) / len(ys)
    pad = 0.08 * max(w, h) + 4
    figw = 8.2
    figh = max(3.6, min(10.5, figw * (h + 2 * pad) / (w + 2 * pad)))
    fig, ax = plt.subplots(figsize=(figw, figh))

    ax.add_patch(MplPoly(parcel_xy, fc=C_LAWN, ec="none", zorder=1))
    # parcellaire privatif : haies entre lots
    for pl in r.get("plots", []):
        for g in _polys(pl):
            hx, hy = g.exterior.xy
            ax.plot(hx, hy, color="#6f9153", lw=1.3, alpha=0.85, zorder=1.7)
    _fill(ax, r.get("zone"), fill=False, ec=C_ZONE, lw=1.1, ls=(0, (6, 4)), alpha=0.6, zorder=1.6)
    _fill(ax, r.get("voirie"), fc=C_ENROBE, ec="none", zorder=2)
    _fill(ax, r.get("parking"), fc=C_ENROBE, ec="#2a2d31", lw=1, zorder=2.1)
    _fill(ax, r.get("mail"), fc=C_MAIL, ec="#b8a271", lw=1, zorder=2.3)
    for seg in r.get("cheminements", []):
        _fill(ax, seg.buffer(0.8, cap_style=2), fc=C_MAIL, ec="none", zorder=2.3)
    for kind, s in r.get("stalls", []):
        ax.add_patch(MplPoly(list(s.exterior.coords),
                     fc=C_GARAGE if kind == "garage" else C_PLACE, ec="white", lw=0.5, zorder=3))

    # arbres dans les jardins (cote oppose au mail), deterministe
    for name, g, log, ent in r["buildings"]:
        c = g.centroid
        dx, dy = c.x - ent[0], c.y - ent[1]
        n = math.hypot(dx, dy) or 1.0
        maxd = max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1])
        tx, ty = c.x + dx / n * (maxd * 0.5 + 2.6), c.y + dy / n * (maxd * 0.5 + 2.6)
        if Polygon(parcel_xy).contains(Point(tx, ty)):
            _tree(ax, tx, ty)

    off = 0.018 * max(w, h) + 0.4
    for name, g, log, ent in r["buildings"]:
        ax.add_patch(MplPoly([(x + off, y - off) for (x, y) in g.exterior.coords],
                     fc="#00000030", ec="none", zorder=4))
    for name, g, log, ent in r["buildings"]:
        ax.add_patch(MplPoly(list(g.exterior.coords), fc=C_ROOF, ec=C_ROOFLINE, lw=1.4, zorder=5))
        _roof(ax, g)
        c = g.centroid
        ax.text(c.x, c.y, f"{name}\n{log} lgt", ha="center", va="center",
                color="white", fontsize=6.3, fontweight="bold", zorder=6)

    if access_pt is not None:
        ax.plot(access_pt[0], access_pt[1], "v", color="#e67e22", ms=15,
                markeredgecolor="white", zorder=7)
        ax.annotate("ACCES", access_pt, textcoords="offset points", xytext=(0, -15),
                    ha="center", color="#d35400", fontsize=8, fontweight="bold", zorder=7)

    # arbres d'alignement le long du perimetre (dans les zones vertes)
    occ = [b[1] for b in r["buildings"]]
    for key in ("parking", "voirie", "mail"):
        if r.get(key) is not None:
            occ.append(r[key])
    occ_u = unary_union(occ) if occ else None
    peri = Polygon(parcel_xy)
    ring = peri.exterior
    ntrees = max(4, int(ring.length / 15))
    for i in range(ntrees):
        pt = ring.interpolate((i + 0.5) / ntrees, normalized=True)
        d = math.hypot(cxp - pt.x, cyp - pt.y) or 1.0
        tx = pt.x + (cxp - pt.x) / d * 3.0
        ty = pt.y + (cyp - pt.y) / d * 3.0
        p2 = Point(tx, ty)
        if peri.contains(p2) and (occ_u is None or not occ_u.buffer(1.5).contains(p2)):
            _tree(ax, tx, ty, r=1.5)

    # limite parcellaire + COTES
    ax.add_patch(MplPoly(parcel_xy, fill=False, ec=C_PARC, lw=3, zorder=8))
    pts = list(parcel_xy)
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1.5:
            continue
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if a > 90 or a < -90:
            a += 180
        nx, ny = -(y2 - y1) / L, (x2 - x1) / L
        if (mx + nx - cxp) ** 2 + (my + ny - cyp) ** 2 < (mx - cxp) ** 2 + (my - cyp) ** 2:
            nx, ny = -nx, -ny
        offd = 0.02 * max(w, h) + 1.3
        ax.text(mx + nx * offd, my + ny * offd, f"{L:.1f} m", ha="center", va="center",
                color=C_PARC, fontsize=6.2, rotation=a, rotation_mode="anchor", zorder=9)

    # echelle graphique
    for cand in (5, 10, 20, 25, 50, 100, 150):
        if cand >= w / 5:
            sb = cand; break
    else:
        sb = 100
    bx = min(xs) - pad * 0.6
    by = min(ys) - pad * 0.55
    ax.plot([bx, bx + sb], [by, by], color="black", lw=3, zorder=10)
    for xt in (bx, bx + sb / 2, bx + sb):
        ax.plot([xt, xt], [by, by + max(w, h) * 0.012], color="black", lw=1.2, zorder=10)
    ax.text(bx + sb / 2, by - max(w, h) * 0.03, f"{sb} m", ha="center", va="top",
            fontsize=7, zorder=10)
    # nord
    ax.annotate("N", xy=(0.965, 0.9), xytext=(0.965, 0.8), xycoords="axes fraction",
                ha="center", fontsize=11, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.6))

    ax.set_aspect("equal")
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.axis("off")
    fig.tight_layout()
    return fig


# ==================================================================
#  INTERFACE STREAMLIT
# ==================================================================
st.set_page_config(page_title="Plan Masse - Carre de l'Habitat", layout="wide")

PRESETS = {
    "Terrain en L (concave)": [(0, 0), (60, 0), (60, 35), (32, 35), (32, 55), (0, 55)],
    "Rectangle 50 x 40":      [(0, 0), (50, 0), (50, 40), (0, 40)],
    "Terrain allonge":        [(0, 0), (15, -25), (120, -10), (130, 30), (60, 40), (10, 30)],
    "Trapeze":                [(0, 0), (65, 0), (50, 45), (10, 45)],
}
DW, DPI = 820, 150

for key, val in {"parcel_df": pd.DataFrame(PRESETS["Terrain en L (concave)"], columns=["x", "y"]),
                 "draw_points": [], "access_px": None, "calib_pts": [], "last_click": None}.items():
    st.session_state.setdefault(key, val)


def load_background(up):
    if up.name.lower().endswith(".pdf"):
        import pymupdf
        pxm = pymupdf.open(stream=up.getvalue(), filetype="pdf")[0].get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pxm.width, pxm.height), pxm.samples)
    else:
        img = Image.open(up).convert("RGB")
    native_w = img.width
    dh = int(img.height * DW / img.width)
    return img.resize((DW, dh)), dh, native_w


st.sidebar.title("Parametres")
mode = st.sidebar.radio("Definir la parcelle", ["Dessiner sur un plan", "Terrains types / coordonnees"])
parcel_xy, access_pt = None, None

if mode == "Dessiner sur un plan":
    st.title("Generateur de faisabilite - Carre de l'Habitat")
    up = st.file_uploader("Importer votre plan - PDF (cadastre) ou image", type=["pdf", "png", "jpg", "jpeg"])
    if up is None:
        st.info("1) importer le plan  2) calibrer (cote de reference : 2 points + longueur reelle)  "
                "3) cliquer les sommets  4) placer l'acces.")
        st.stop()
    base, dh, native_w = load_background(up)
    is_pdf = up.name.lower().endswith(".pdf")
    st.subheader("Calibrage & trace")

    # --- ECHELLE ---
    mpp_auto = None
    if is_pdf:
        echelle = st.number_input("Echelle d'edition du PDF (1 : ?)", min_value=50, value=500,
                                  step=50, help="Ex. cadastre = 1:500. Calage automatique, sans mesure.")
        mpp_auto = echelle * 0.0254 / DPI * (native_w / DW)   # exact pour un PDF a l'echelle

    action = st.radio("Le clic sert a :", ["Cote de reference (2 points)", "Sommet de la parcelle",
                                           "Placer l'acces voiture"], horizontal=True)
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Annuler sommet") and st.session_state.draw_points:
        st.session_state.draw_points.pop()
    if c2.button("Effacer parcelle"):
        st.session_state.draw_points = []
    if c3.button("Effacer calibrage"):
        st.session_state.calib_pts = []
    ferme = c4.checkbox("Fermer la parcelle", value=True)

    calib, mpp = st.session_state.calib_pts, None
    if len(calib) == 2:
        longueur = st.number_input("Longueur reelle de ce segment (metres)", min_value=0.10,
                                   value=20.0, step=0.10, format="%.2f")
        pixd = math.dist(calib[0], calib[1])
        if pixd > 1:
            mpp = longueur / pixd
            st.success(f"Echelle CALIBREE (prioritaire) : plan affiche = {DW * mpp:.1f} m de large.")
    if mpp is None and mpp_auto is not None:
        mpp = mpp_auto
        st.success(f"Echelle AUTOMATIQUE (1:{echelle}) : plan affiche = {DW * mpp:.1f} m de large. "
                   f"Aucune mesure requise. (Verifiable ci-dessous ; sinon, posez une cote de reference.)")
    elif mpp is None:
        st.warning("Image sans echelle : posez une cote de reference (2 points + longueur).")

    disp = base.copy(); d = ImageDraw.Draw(disp)
    pts = st.session_state.draw_points
    if len(pts) >= 2:
        d.line(pts + ([pts[0]] if ferme and len(pts) >= 3 else []), fill=(230, 80, 30), width=3)
    for (px, py) in pts:
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(230, 80, 30), outline="white")
    if len(calib) >= 1:
        if len(calib) == 2:
            d.line(calib, fill=(20, 130, 200), width=4)
        for (px, py) in calib:
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(20, 130, 200), outline="white")
    if st.session_state.access_px is not None:
        px, py = st.session_state.access_px
        d.polygon([(px, py - 10), (px - 9, py + 8), (px + 9, py + 8)], fill=(230, 140, 0), outline="white")

    val = streamlit_image_coordinates(disp, key="plan")
    if val is not None:
        click = (int(val["x"]), int(val["y"]))
        if click != st.session_state.last_click:
            st.session_state.last_click = click
            if action == "Cote de reference (2 points)":
                if len(st.session_state.calib_pts) >= 2:
                    st.session_state.calib_pts = []
                st.session_state.calib_pts.append(click)
            elif action == "Sommet de la parcelle":
                st.session_state.draw_points.append(click)
            else:
                st.session_state.access_px = click
            st.rerun()

    if mpp is None or len(pts) < 3:
        if mpp is not None:
            st.info(f"{len(pts)} sommet(s) - cliquez au moins 3 sommets.")
        st.stop()

    to_m = lambda px, py: (px * mpp, (dh - py) * mpp)
    parcel_xy = [to_m(px, py) for (px, py) in pts]
    # verification d'echelle : longueurs des cotes
    edges = []
    for i in range(len(parcel_xy)):
        a, b = parcel_xy[i], parcel_xy[(i + 1) % len(parcel_xy)]
        edges.append(round(math.dist(a, b), 1))
    with st.expander("Verifier l'echelle (longueurs des cotes traces)"):
        st.write("Longueurs (m) : " + "  |  ".join(f"cote {i+1}: {e}" for i, e in enumerate(edges)))
        st.caption("Comparez a votre plan. Si c'est faux, refaites la cote de reference.")
    if st.session_state.access_px is not None:
        access_pt = to_m(*st.session_state.access_px)
    else:
        a, b = parcel_xy[0], parcel_xy[1]
        access_pt = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

else:
    st.title("Generateur de faisabilite - Carre de l'Habitat")
    st.sidebar.subheader("1. Parcelle")
    preset = st.sidebar.selectbox("Charger un terrain type", list(PRESETS.keys()))
    if st.sidebar.button("Charger ce terrain"):
        st.session_state.parcel_df = pd.DataFrame(PRESETS[preset], columns=["x", "y"])
    st.sidebar.caption("Sommets en metres (X est, Y nord), dans l'ordre du contour.")
    df = st.sidebar.data_editor(st.session_state.parcel_df, num_rows="dynamic", width="stretch",
                                key="editor",
                                column_config={"x": st.column_config.NumberColumn("X (m)"),
                                               "y": st.column_config.NumberColumn("Y (m)")})
    parcel_xy = [(float(row.x), float(row.y)) for row in df.itertuples()]
    st.sidebar.subheader("2. Acces sur rue")
    cc1, cc2 = st.sidebar.columns(2)
    axv = cc1.number_input("Acces X", value=30.0)
    ayv = cc2.number_input("Acces Y", value=0.0)
    if len(parcel_xy) >= 3:
        try:
            snap = nearest_points(Polygon(parcel_xy).exterior, Point(axv, ayv))[0]
            access_pt = (snap.x, snap.y)
        except Exception:
            access_pt = None

st.sidebar.subheader("3. Regles PLU")
retrait = st.sidebar.slider("Retrait limites separatives (m)", 0.0, 15.0, 4.0, 0.5)
retrait_voie = st.sidebar.slider("Retrait voirie / alignement (m)", 0.0, 15.0, 5.0, 0.5)
dist_inter = st.sidebar.slider("Distance batiments / jardins (m)", 3.0, 15.0, 6.0, 0.5)
ces_max = st.sidebar.slider("Emprise au sol max - CES (%)", 5, 100, 100, 5) / 100.0
ev_min = st.sidebar.slider("Espaces verts min (%)", 0, 80, 0, 5) / 100.0
voirie_larg = st.sidebar.slider("Largeur voirie carrossable (m)", 3.0, 8.0, 5.0, 0.5)
mail_larg = st.sidebar.slider("Largeur mail pietonnier (m)", 1.5, 6.0, 3.0, 0.5)

st.sidebar.subheader("4. Produits autorises")
enabled = [n for n in BUILDINGS if st.sidebar.checkbox(
    f"{n} ({BUILDINGS[n]['log']} lgt - {BUILDINGS[n]['w']}x{BUILDINGS[n]['h']}m)",
    value=True, key=f"bat_{n}")]
if enabled:
    st.sidebar.caption("Produits actifs : " + ", ".join(enabled))

ok = parcel_xy is not None and len(parcel_xy) >= 3
if ok:
    try:
        Polygon(parcel_xy)
    except Exception:
        ok = False
if not ok:
    st.warning("Definis au moins 3 sommets valides."); st.stop()
if not enabled:
    st.warning("Coche au moins un produit."); st.stop()
if access_pt is None:
    access_pt = list(Polygon(parcel_xy).centroid.coords)[0]

result = compute_feasibility(parcel_xy, access_pt, {
    "retrait_sep": retrait, "retrait_voie": retrait_voie, "dist_inter": dist_inter,
    "ces_max": ces_max, "espaces_verts_min": ev_min, "voirie_larg": voirie_larg,
    "mail_larg": mail_larg, "enabled": enabled})
k = result["kpis"]

st.subheader("Plan-masse")
cp, ck = st.columns([3, 2])
with cp:
    st.pyplot(render_plan(result, parcel_xy, access_pt))
with ck:
    if result["message"]:
        st.error(result["message"])
    if not k.get("stationnement_suffisant", True):
        st.warning(f"Stationnement insuffisant : {k['logements_non_stationnes']} lgt.")
    if not k.get("ces_respecte", True):
        st.warning(f"CES depasse : {k['emprise_au_sol_pct']} %.")
    if not k.get("espaces_verts_respecte", True):
        st.warning(f"Espaces verts insuffisants : {k['espaces_verts_pct']} %.")
    st.subheader("Indicateurs")
    a, b = st.columns(2)
    a.metric("Logements", k["nb_logements"])
    b.metric("Places / Garages", f'{k["nb_places"]} / {k["nb_garages"]}')
    a.metric("Surface parcelle", f'{k["surface_parcelle_m2"]:.0f} m2')
    b.metric("Surface batie", f'{k["surface_batie_m2"]:.0f} m2')
    a.metric("Emprise au sol", f'{k["emprise_au_sol_pct"]:.1f} %')
    b.metric("Espaces verts", f'{k["espaces_verts_pct"]:.1f} %')
    a.metric("Voirie (ml)", f'{k["ml_voirie"]:.0f} m')
    b.metric("VRD / logement", f'{k["ratio_vrd_par_logement_m2"]:.0f} m2')

st.caption("Fichier unique autonome - moteur generatif (mail + rangees), VRD minimise, "
           "echelle par cote de reference verifiable.")
