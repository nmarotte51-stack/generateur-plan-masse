"""
Moteur de faisabilite - Generateur Plan Masse "Carre de l'Habitat"
==================================================================
Conception GENERATIVE deterministe orientee metier (developpement foncier).

Principe (et non plus du bin-packing) :
  Acces  ->  Voirie courte  ->  Poche de stationnement GROUPEE
         ->  MAIL pietonnier central (colonne vertebrale)
         ->  Batiments standard (KAIA/NAIA/DAIA/TAIA) en RANGEES se faisant face
             de part et d'autre du mail, entree au milieu de la facade sur mail,
             jardins prives dans l'espace restant.

Objectif economique : maximiser les logements en MINIMISANT le VRD (voirie/reseaux).
Toute la geometrie robuste s'appuie sur Shapely (offsets, booleens, collisions).
"""
import math
from shapely.geometry import Polygon, box, Point, LineString
from shapely.affinity import rotate
from shapely.ops import unary_union

from paths import central_axis, build_circulation

# ------------------------------------------------------------------
# 1. CATALOGUE PRODUITS (ref PLU Carre de l'Habitat)
# ------------------------------------------------------------------
BUILDINGS = {
    "KAIA": {"w": 14.20, "h": 15.80, "log": 4},   # 4 T4
    "NAIA": {"w": 15.80, "h": 15.80, "log": 4},   # 4 T4
    "DAIA": {"w":  8.10, "h": 14.20, "log": 2},   # 2 T4
    "TAIA": {"w":  8.10, "h": 21.14, "log": 3},   # 3 T4
}
PLACE  = {"w": 2.50, "d": 5.00}
GARAGE = {"w": 2.78, "d": 5.50}
ALLEE  = 5.50

DEFAULTS = {
    "retrait_sep": 3.0, "retrait_voie": 5.0, "dist_inter": 5.0,
    "ces_max": 1.0, "espaces_verts_min": 0.0, "voirie_larg": 5.0,
    "mail_larg": 3.0, "enabled": list(BUILDINGS.keys()),
}


# ------------------------------------------------------------------
# 2. OUTILS GEOMETRIQUES
# ------------------------------------------------------------------
def _largest(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    return None


def longest_edge_angle(poly):
    """Angle (deg) du plus long cote -> oriente le mail et les rangees."""
    xy = list(poly.exterior.coords)
    best_len, best_ang = 0.0, 0.0
    for i in range(len(xy) - 1):
        (x1, y1), (x2, y2) = xy[i], xy[i + 1]
        L = math.hypot(x2 - x1, y2 - y1)
        if L > best_len:
            best_len, best_ang = L, math.degrees(math.atan2(y2 - y1, x2 - x1))
    return best_ang


def _road_edge(parcel_xy, access_pt):
    poly = Polygon(parcel_xy)
    ap = Point(access_pt)
    xy = list(poly.exterior.coords)
    best, bd = None, 1e18
    for i in range(len(xy) - 1):
        seg = LineString([xy[i], xy[i + 1]])
        d = seg.distance(ap)
        if d < bd:
            bd, best = d, seg
    return best


def constructible_zone(parcel_xy, retrait_separatif, retrait_voie=None, access_pt=None):
    """Zone constructible = parcelle - retrait separatif, avec retrait voirie en
    plus le long du bord d'acces. Buffer negatif robuste (Shapely)."""
    poly = Polygon(parcel_xy)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zc = _largest(poly.buffer(-retrait_separatif, join_style=2, mitre_limit=5.0))
    if zc is None:
        return None
    if retrait_voie and access_pt is not None and retrait_voie > retrait_separatif:
        strip = _road_edge(parcel_xy, access_pt).buffer(retrait_voie)
        zc = _largest(zc.difference(strip))
    return zc


# ------------------------------------------------------------------
# 3. POCHE DE STATIONNEMENT GROUPEE (a l'acces)
#    Places (parking ouvert) tolerees dans le retrait -> contrainte parcelle.
#    Garages -> contrainte zone constructible. Colonnes toujours equilibrees.
# ------------------------------------------------------------------
def parking_pocket(zone, parcel, access_pt, n_log, angle_deg):
    if n_log <= 0 or zone is None:
        return None, []
    gd, pd = GARAGE["d"], PLACE["d"]
    depth = gd + ALLEE + pd
    col_w = max(GARAGE["w"], PLACE["w"])
    cx, cy = parcel.centroid.x, parcel.centroid.y
    zr = rotate(zone, -angle_deg, origin=(cx, cy))
    pr = rotate(parcel, -angle_deg, origin=(cx, cy))
    ax = rotate(Point(access_pt), -angle_deg, origin=(cx, cy))
    pminx, pminy, pmaxx, pmaxy = pr.bounds
    if abs(ax.y - pminy) <= abs(ax.y - pmaxy):
        y0, direction = pminy, +1.0
    else:
        y0, direction = pmaxy - depth, -1.0
    stalls, rects, placed, bays = [], [], 0, 0
    while placed < n_log and bays < 8:
        bays += 1
        if y0 < pminy - 1e-6 or y0 + depth > pmaxy + 1e-6:
            break
        if direction > 0:
            place_y, garage_y = y0, y0 + pd + ALLEE
        else:
            place_y, garage_y = y0 + depth - pd, y0
        cols, x = [], pminx
        while x + col_w <= pmaxx + 1e-6:
            pl = box(x, place_y, x + PLACE["w"], place_y + pd)
            gar = box(x, garage_y, x + GARAGE["w"], garage_y + gd)
            if pr.contains(pl.buffer(-1e-6)) and zr.contains(gar.buffer(-1e-6)):
                cols.append((x, gar, pl))
            x += col_w
        if cols:
            need = n_log - placed
            cols.sort(key=lambda c: abs((c[0] + col_w / 2) - ax.x))
            take = sorted(cols[:need], key=lambda c: c[0])
            for _, g, pcell in take:
                stalls += [("garage", g), ("place", pcell)]
                placed += 1
            xs0 = min(c[0] for c in take)
            xs1 = max(c[0] for c in take) + col_w
            rects.append(box(xs0, y0, xs1, y0 + depth))
        y0 += depth * direction
    if not stalls:
        return None, []
    bay = unary_union(rects).intersection(pr)
    bay = rotate(bay, angle_deg, origin=(cx, cy))
    stalls = [(k, rotate(s, angle_deg, origin=(cx, cy))) for k, s in stalls]
    return bay, stalls


# ------------------------------------------------------------------
# 4. IMPLANTATION EN RANGEES LE LONG DU MAIL (repere pivote)
# ------------------------------------------------------------------
def _orientations(b):
    o = [(b["w"], b["h"]), (b["h"], b["w"])]
    return o if o[0] != o[1] else [o[0]]


def _place_row(zone_r, pocket_r, placed_all, side, near_y, x_lo, x_hi,
               types_sorted, gap, zy0, zy1, step=1.0):
    """Place une rangee : facade sur mail alignee sur 'near_y', batiments
    s'etendant du cote 'side' (+1 au-dessus du mail, -1 en dessous)."""
    placed = []
    x = x_lo
    while x < x_hi:
        best = None
        for name in types_sorted:
            b = BUILDINGS[name]
            for (wx, wy) in _orientations(b):
                if side > 0:
                    y0, y1 = near_y, near_y + wy
                else:
                    y0, y1 = near_y - wy, near_y
                if y0 < zy0 - 1e-6 or y1 > zy1 + 1e-6 or x + wx > x_hi + 1e-6:
                    continue
                foot = box(x, y0, x + wx, y1)
                if not zone_r.contains(foot.buffer(-0.05)):
                    continue
                if pocket_r is not None and foot.distance(pocket_r) < gap:
                    continue
                if any(foot.distance(f) < gap - 1e-6 for f in placed_all):
                    continue
                entrance = (x + wx / 2, near_y)
                best = (name, foot, b["log"], entrance, wx)
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


def _layout_for_angle(parcel, zone, access_pt, angle, p):
    """Genere l'amenagement complet pour une orientation de mail donnee.
    Tout est calcule en repere pivote (mail horizontal) puis rebascule."""
    origin = zone.centroid.coords[0]
    R = lambda g: rotate(g, -angle, origin=origin)
    Rb = lambda g: rotate(g, angle, origin=origin)

    zone_r = R(zone)
    zx0, zy0, zx1, zy1 = zone_r.bounds

    gap = p["dist_inter"]
    mail_w = p["mail_larg"]
    walk = max(1.2, (gap - mail_w) / 2 + 0.5)      # profondeur cheminement secondaire
    types_sorted = sorted(p["enabled"], key=lambda t: -BUILDINGS[t]["log"])
    ces_cap = p["ces_max"] * parcel.area if p["ces_max"] < 1.0 else float("inf")

    def cap_ces(bldgs):
        bldgs = sorted(bldgs, key=lambda b: -b[1].area)
        kept, surf = [], 0.0
        for b in bldgs:
            if surf + b[1].area <= ces_cap + 1e-6:
                kept.append(b); surf += b[1].area
        return kept

    def do_rows(pocket_r, mail_y):
        near_up = mail_y + mail_w / 2 + walk
        near_dn = mail_y - mail_w / 2 - walk
        placed_all = []
        up = _place_row(zone_r, pocket_r, placed_all, +1, near_up, zx0, zx1,
                        types_sorted, gap, zy0, zy1)
        dn = _place_row(zone_r, pocket_r, placed_all, -1, near_dn, zx0, zx1,
                        types_sorted, gap, zy0, zy1)
        return up + dn

    # mail central : a mi-hauteur de la zone (rangees equilibrees des deux cotes)
    mail_y = (zy0 + zy1) / 2.0

    # point fixe poche <-> rangees (la poche depend du nb de logements)
    rows = cap_ces(do_rows(None, mail_y))
    L = sum(b[2] for b in rows)
    bay, stalls = None, []
    for _ in range(6):
        bay, stalls = parking_pocket(zone, parcel, access_pt, max(L, 1), angle)
        pocket_r = R(bay) if bay is not None else None
        rows2 = cap_ces(do_rows(pocket_r, mail_y))
        L2 = sum(b[2] for b in rows2)
        if L2 == L:
            rows = rows2
            break
        rows, L = rows2, L2

    if not rows:
        return {"buildings": [], "L": 0, "parking": bay, "stalls": stalls,
                "voirie": None, "mail": None, "cheminements": [], "corridors": []}

    # geometrie du mail : de la poche jusqu'au dernier batiment
    xs_centers = [b[3][0] for b in rows]
    x_lo = min(xs_centers)
    x_hi = max(xs_centers)
    if bay is not None:
        x_lo = min(x_lo, R(bay).centroid.x)
    mail_r = box(x_lo, mail_y - mail_w / 2, x_hi, mail_y + mail_w / 2).intersection(zone_r)

    # circulation (mail + antennes orthogonales) construite en repere pivote
    entrances_r = [(b[3][0], b[3][1]) for b in rows]
    sides = [1 if b[3][1] > mail_y else -1 for b in rows]
    mail_world, stubs_world = build_circulation(mail_r, entrances_r, sides, mail_y,
                                                mail_w, Rb)

    buildings_world = [(b[0], Rb(b[1]), b[2], Rb(Point(b[3])).coords[0]) for b in rows]
    corridors = [central_axis(bw[1]) for bw in buildings_world]

    # voirie : acces -> poche (courte, pour limiter l'enrobe)
    voirie = None
    if bay is not None:
        voirie = LineString([access_pt, (bay.centroid.x, bay.centroid.y)]).buffer(
            p["voirie_larg"] / 2, cap_style=2).intersection(parcel)
        if voirie.is_empty:
            voirie = None

    return {"buildings": buildings_world, "L": sum(b[2] for b in buildings_world),
            "parking": bay, "stalls": stalls, "voirie": voirie,
            "mail": mail_world, "cheminements": stubs_world, "corridors": corridors}


# ------------------------------------------------------------------
# 5. PIPELINE PRINCIPAL
# ------------------------------------------------------------------
def compute_feasibility(parcel_xy, access_pt, params):
    p = dict(DEFAULTS)
    p.update(params or {})
    parcel = Polygon(parcel_xy)
    if access_pt is None:
        access_pt = list(parcel.centroid.coords)[0]

    zone = constructible_zone(parcel_xy, p["retrait_sep"], p["retrait_voie"], access_pt)
    result = {"parcel": parcel, "zone": zone, "access": access_pt, "params": p,
              "buildings": [], "parking": None, "stalls": [], "voirie": None,
              "mail": None, "cheminements": [], "corridors": [], "espaces_verts": None,
              "message": None}

    if zone is None or zone.area < 5:
        result["message"] = "Zone constructible vide (retraits trop forts ou terrain trop petit)."
        result["kpis"] = _kpis(result)
        return result
    if not p["enabled"]:
        result["message"] = "Aucun type de batiment autorise."
        result["kpis"] = _kpis(result)
        return result

    # teste l'orientation du mail : plus long cote de la zone, et sa perpendiculaire
    base = longest_edge_angle(zone)
    best = None
    for ang in (base, base + 90.0):
        lay = _layout_for_angle(parcel, zone, access_pt, ang, p)
        if best is None or lay["L"] > best["L"]:
            best, best_ang = lay, ang

    result.update(buildings=best["buildings"], parking=best["parking"],
                  stalls=best["stalls"], voirie=best["voirie"], mail=best["mail"],
                  cheminements=best["cheminements"], corridors=best["corridors"],
                  angle=best_ang)

    if not best["buildings"]:
        result["message"] = "Terrain trop petit ou contraintes trop fortes (aucun batiment plaçable)."

    # espaces verts / jardins = parcelle - (bati + poche + voirie + mail + antennes)
    occupe = [b[1] for b in best["buildings"]]
    if best["parking"] is not None:
        occupe.append(best["parking"])
    if best["voirie"] is not None:
        occupe.append(best["voirie"])
    if best["mail"] is not None:
        occupe.append(best["mail"])
    occupe += [s.buffer(0.6) for s in best["cheminements"]]
    verts = parcel.difference(unary_union(occupe)) if occupe else parcel
    result["espaces_verts"] = _largest(verts) if verts and not verts.is_empty else None
    result["espaces_verts_all"] = verts

    result["kpis"] = _kpis(result)
    return result


def _kpis(r):
    p = r.get("params", {})
    sp = r["parcel"].area
    s_bati = sum(b[1].area for b in r["buildings"])
    n_log = sum(b[2] for b in r["buildings"])
    n_gar = sum(1 for k, _ in r["stalls"] if k == "garage")
    n_pl = sum(1 for k, _ in r["stalls"] if k == "place")
    s_poche = r["parking"].area if r.get("parking") else 0.0
    s_voirie = r["voirie"].area if r.get("voirie") else 0.0
    s_mail = r["mail"].area if r.get("mail") else 0.0
    s_verts = r["espaces_verts_all"].area if r.get("espaces_verts_all") else \
        max(0.0, sp - s_bati - s_poche - s_voirie - s_mail)
    ml_voirie = 0.0
    if r.get("voirie") is not None and p.get("voirie_larg"):
        ml_voirie = s_voirie / max(p["voirie_larg"], 0.1)
    stationne = min(n_gar, n_pl)
    emp = (s_bati / sp * 100) if sp else 0
    ev = (s_verts / sp * 100) if sp else 0
    ces_max = p.get("ces_max", 1.0) * 100
    ev_min = p.get("espaces_verts_min", 0.0) * 100
    return {
        "surface_parcelle_m2": round(sp, 1),
        "surface_batie_m2": round(s_bati, 1),
        "surface_espaces_verts_m2": round(s_verts, 1),
        "surface_poche_stationnement_m2": round(s_poche, 1),
        "surface_voirie_m2": round(s_voirie, 1),
        "surface_mail_m2": round(s_mail, 1),
        "ml_voirie": round(ml_voirie, 1),
        "nb_logements": n_log,
        "nb_places": n_pl,
        "nb_garages": n_gar,
        "emprise_au_sol_pct": round(emp, 1),
        "espaces_verts_pct": round(ev, 1),
        "ratio_vrd_par_logement_m2": round((s_poche + s_voirie + s_mail) / n_log, 1) if n_log else 0,
        "ces_respecte": emp <= ces_max + 0.1,
        "espaces_verts_respecte": ev >= ev_min - 0.1,
        "stationnement_suffisant": stationne >= n_log,
        "logements_non_stationnes": max(0, n_log - stationne),
    }
