"""
Moteur de faisabilite - Generateur Plan Masse "Carre de l'Habitat"
------------------------------------------------------------------
Coeur geometrique en Python + Shapely.

Pourquoi Python/Shapely : le calcul de la zone constructible (retraits)
est un 'offset' de polygone. Shapely le fait de facon robuste, y compris
sur les parcelles concaves et les grands retraits (auto-intersections
gerees automatiquement) - la ou la version JS 'faite main' cassait.

L'interface (dessin, canvas, KPI) reste separee. Ce module ne fait QUE
le calcul, il rend des geometries + des chiffres. Il est volontairement
compact pour etre teste et corrige par petites touches.
"""

import math
from shapely.geometry import Polygon, box, Point, LineString
from shapely.affinity import rotate, translate
from shapely.ops import unary_union
from paths import find_paths

# ------------------------------------------------------------------
# 1. CATALOGUE (la donnee, depuis ta spec)
# ------------------------------------------------------------------
BUILDINGS = {
    "KAIA": {"w": 14.20, "h": 15.80, "log": 4},   # 4 T4
    "NAIA": {"w": 15.80, "h": 15.80, "log": 4},   # 4 T4 (ref PLU : 4 lgt, pas 5)
    "DAIA": {"w":  8.10, "h": 14.20, "log": 2},   # 2 T4
    "TAIA": {"w":  8.10, "h": 21.14, "log": 3},   # 3 T4
}
PLACE  = {"w": 2.50, "d": 5.00}   # place standard
GARAGE = {"w": 2.78, "d": 5.50}   # garage box
ALLEE  = 5.50                      # allee centrale de la poche (5 a 6 m)


# ------------------------------------------------------------------
# 2. OUTILS GEOMETRIQUES
# ------------------------------------------------------------------
def _largest(geom):
    """Renvoie le plus grand polygone (un buffer negatif peut en produire
    plusieurs, ou zero si le retrait 'mange' toute la parcelle)."""
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    return None


def dominant_angle_deg(poly):
    """Angle (en degres) du plus long cote de la parcelle. Sert a aligner
    harmonieusement les batiments sur l'orientation dominante du terrain."""
    xy = list(poly.exterior.coords)
    best_len, best_ang = 0.0, 0.0
    for i in range(len(xy) - 1):
        (x1, y1), (x2, y2) = xy[i], xy[i + 1]
        L = math.hypot(x2 - x1, y2 - y1)
        if L > best_len:
            best_len = L
            best_ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
    return best_ang


def _road_edge(parcel_xy, access_pt):
    """Bord de parcelle (segment) le plus proche de l'acces = la rue."""
    poly = Polygon(parcel_xy)
    ap = Point(access_pt)
    xy = list(poly.exterior.coords)
    best, bd = None, 1e18
    for i in range(len(xy) - 1):
        seg = LineString([xy[i], xy[i + 1]])
        dd = seg.distance(ap)
        if dd < bd:
            bd, best = dd, seg
    return best


def constructible_zone(parcel_xy, retrait_separatif, retrait_voie=None, access_pt=None):
    """Zone constructible = parcelle retrecie du retrait separatif, avec un
    retrait VOIRIE (souvent different) applique en plus le long du bord d'acces
    (la rue). Buffer negatif robuste (Shapely gere concavites/auto-intersections)."""
    poly = Polygon(parcel_xy)
    if not poly.is_valid:
        poly = poly.buffer(0)          # repare les auto-intersections du trace
    zc = _largest(poly.buffer(-retrait_separatif, join_style=2, mitre_limit=5.0))
    if zc is None:
        return None
    if retrait_voie and access_pt is not None and retrait_voie > retrait_separatif:
        strip = _road_edge(parcel_xy, access_pt).buffer(retrait_voie)
        zc = _largest(zc.difference(strip))
    return zc


# ------------------------------------------------------------------
# 3. PLACEMENT DES BATIMENTS (heuristique v1 : rangees alignees)
# ------------------------------------------------------------------
def _fits(cand, buildable, placed, dist_inter):
    if not buildable.contains(cand.buffer(-1e-6)):
        return False
    for _, g, _ in placed:
        if cand.distance(g) < dist_inter - 1e-6:
            return False
    return True


def place_buildings(buildable, enabled, dist_inter, angle_deg, step=1.5):
    """Range les batiments en rangees paralleles a l'orientation dominante.
    On travaille dans un repere pivote (terrain 'a plat'), on remplit en
    grille, puis on repivote. Resultat : implantation alignee et lisible."""
    if buildable is None or buildable.is_empty:
        return []

    cx, cy = buildable.centroid.x, buildable.centroid.y
    b_rot = rotate(buildable, -angle_deg, origin=(cx, cy))
    minx, miny, maxx, maxy = b_rot.bounds

    # types les plus 'denses' en logements d'abord (max logements au sol)
    types = sorted(enabled, key=lambda t: BUILDINGS[t]["log"] / (BUILDINGS[t]["w"] * BUILDINGS[t]["h"]), reverse=True)

    placed = []  # (name, polygon_rot, log)
    for name in types:
        b = BUILDINGS[name]
        for (w, h) in [(b["w"], b["h"]), (b["h"], b["w"])]:
            y = miny
            while y + h <= maxy + 1e-6:
                x = minx
                while x + w <= maxx + 1e-6:
                    cand = box(x, y, x + w, y + h)
                    if _fits(cand, b_rot, placed, dist_inter):
                        placed.append((name, cand, b["log"]))
                        x += w + dist_inter
                    else:
                        x += step
                y += step               # balayage fin : trouve toute bande libre

    # repivote vers le repere reel
    return [(name, rotate(g, angle_deg, origin=(cx, cy)), log) for name, g, log in placed]


# ------------------------------------------------------------------
# 4. POCHE DE STATIONNEMENT (v1 : baie double, pres de l'acces)
# ------------------------------------------------------------------
def parking_pocket(zone, parcel, access_pt, n_log, angle_deg):
    """Poche de stationnement compacte, empilee en profondeur depuis le bord
    de l'acces. Regle metier : les PLACES (parking ouvert) peuvent empieter sur
    le retrait separatif -> elles sont contraintes par la PARCELLE ; les GARAGES
    doivent rester hors retrait -> contraints par la ZONE constructible.
    On dispose donc la rangee de places cote rue (peut mordre le retrait) et la
    rangee de garages plus au fond (dans la zone). Colonnes toujours equilibrees
    (1 garage + 1 place)."""
    if n_log <= 0 or zone is None:
        return None, []

    gd, pd = GARAGE["d"], PLACE["d"]
    depth = gd + ALLEE + pd
    col_w = max(GARAGE["w"], PLACE["w"])

    cx, cy = parcel.centroid.x, parcel.centroid.y
    zone_rot = rotate(zone, -angle_deg, origin=(cx, cy))
    parcel_rot = rotate(parcel, -angle_deg, origin=(cx, cy))
    ax = rotate(Point(access_pt), -angle_deg, origin=(cx, cy))
    pminx, pminy, pmaxx, pmaxy = parcel_rot.bounds

    # cote acces (bord de parcelle) et sens de progression vers l'interieur
    if abs(ax.y - pminy) <= abs(ax.y - pmaxy):
        y0, direction = pminy, +1.0        # rue en bas : places en bas, garages au-dessus
    else:
        y0, direction = pmaxy - depth, -1.0

    stalls, bay_rects, placed, bays = [], [], 0, 0
    while placed < n_log and bays < 8:
        bays += 1
        if y0 < pminy - 1e-6 or y0 + depth > pmaxy + 1e-6:
            break
        # rangee places cote bord, rangee garages cote interieur
        if direction > 0:
            place_y, garage_y = y0, y0 + pd + ALLEE
        else:
            place_y, garage_y = y0 + depth - pd, y0
        cols, x = [], pminx
        while x + col_w <= pmaxx + 1e-6:
            pl = box(x, place_y, x + PLACE["w"], place_y + pd)
            gar = box(x, garage_y, x + GARAGE["w"], garage_y + gd)
            # place : dans la parcelle (retrait autorise) ; garage : dans la zone
            if parcel_rot.contains(pl.buffer(-1e-6)) and zone_rot.contains(gar.buffer(-1e-6)):
                cols.append((x, gar, pl))
            x += col_w
        if cols:
            need = n_log - placed
            cols.sort(key=lambda c: abs((c[0] + col_w / 2) - ax.x))  # proches de l'acces
            take = sorted(cols[:need], key=lambda c: c[0])
            for _, g, pcell in take:
                stalls += [("garage", g), ("place", pcell)]
                placed += 1
            xs0 = min(c[0] for c in take)
            xs1 = max(c[0] for c in take) + col_w
            bay_rects.append(box(xs0, y0, xs1, y0 + depth))
        y0 += depth * direction

    if not stalls:
        return None, []

    bay = unary_union(bay_rects).intersection(parcel_rot)   # clip a la parcelle
    bay = rotate(bay, angle_deg, origin=(cx, cy))
    stalls = [(k, rotate(s, angle_deg, origin=(cx, cy))) for k, s in stalls]
    return bay, stalls


# ------------------------------------------------------------------
# 5. PIPELINE COMPLET + boucle d'ajustement bornee
# ------------------------------------------------------------------
def compute_feasibility(parcel_xy, access_pt, params):
    p = {"retrait_sep": 3.0, "retrait_voie": 5.0, "dist_inter": 4.0,
         "ces_max": 1.0, "espaces_verts_min": 0.0, "voirie_larg": 5.0,
         "enabled": list(BUILDINGS.keys())}
    p.update(params or {})

    parcel = Polygon(parcel_xy)
    angle = dominant_angle_deg(parcel)
    if access_pt is None:
        access_pt = list(parcel.centroid.coords)[0]
    zone = constructible_zone(parcel_xy, p["retrait_sep"], p["retrait_voie"], access_pt)

    result = {"parcel": parcel, "zone": zone, "buildings": [], "parking": None,
              "stalls": [], "corridors": [], "cheminements": [], "voirie": None,
              "angle": angle, "params": p, "message": None}

    if zone is None or zone.area < 1:
        result["message"] = "Terrain trop petit ou retraits trop forts (zone constructible vide)."
        result["kpis"] = _kpis(result)
        return result

    # plafond CES : emprise batie maxi = ces_max * surface parcelle
    ces_cap_m2 = p["ces_max"] * parcel.area if p["ces_max"] < 1.0 else float("inf")

    def buildable_for(Ltarget):
        bay, _ = parking_pocket(zone, parcel, access_pt, Ltarget, angle)
        if bay is None:
            return zone, None
        area = _largest(zone.difference(bay.buffer(p["dist_inter"])))
        return (area or zone), bay

    def cap_ces(bldgs):
        """Retire des batiments (plus petits d'abord) tant que l'emprise > CES."""
        bldgs = sorted(bldgs, key=lambda b: -b[1].area)   # garde les gros d'abord
        kept, surf = [], 0.0
        for b in bldgs:
            if surf + b[1].area <= ces_cap_m2 + 1e-6:
                kept.append(b); surf += b[1].area
        return kept

    def capacity(Ltarget, step):
        area, _ = buildable_for(Ltarget)
        b = place_buildings(area, p["enabled"], p["dist_inter"], angle, step=step)
        return sum(x[2] for x in cap_ces(b))

    L0 = capacity(0, step=2.5)
    lo, hi, L_star = 0, L0, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if capacity(mid, step=2.5) >= mid:
            L_star, lo = mid, mid + 1
        else:
            hi = mid - 1

    L, buildings = L_star, []
    for _ in range(6):
        area, _ = buildable_for(L)
        buildings = cap_ces(place_buildings(area, p["enabled"], p["dist_inter"], angle, step=1.0))
        Lf = sum(b[2] for b in buildings)
        if Lf == L:
            break
        L = Lf
    L_final = sum(b[2] for b in buildings)
    bay, stalls = parking_pocket(zone, parcel, access_pt, L_final, angle)
    if bay is not None and any(b[1].intersects(bay.buffer(p["dist_inter"])) for b in buildings):
        bay, stalls = parking_pocket(zone, parcel, access_pt, L, angle)

    if not buildings:
        result["message"] = "Terrain trop petit ou contraintes trop fortes (aucun batiment plaçable)."

    # voirie : tiree depuis l'acces jusqu'a la poche de stationnement
    voirie = None
    if bay is not None:
        target = bay.centroid
        voirie = LineString([access_pt, (target.x, target.y)]).buffer(
            p["voirie_larg"] / 2, cap_style=2).intersection(parcel)
        if voirie.is_empty:
            voirie = None

    corridors, cheminements = ([], [])
    if buildings and bay is not None:
        corridors, cheminements = find_paths(zone, buildings, bay, stalls,
                                             angle_deg=angle, dist_inter=p["dist_inter"])

    result.update(buildings=buildings, parking=bay, stalls=stalls, voirie=voirie,
                  corridors=corridors, cheminements=cheminements)
    result["kpis"] = _kpis(result)
    return result


def _kpis(r):
    p = r.get("params", {})
    surf_parcelle = r["parcel"].area
    surf_bati = sum(b[1].area for b in r["buildings"])
    n_log = sum(b[2] for b in r["buildings"])
    n_gar = sum(1 for k, _ in r["stalls"] if k == "garage")
    n_pl = sum(1 for k, _ in r["stalls"] if k == "place")
    surf_poche = r["parking"].area if r["parking"] else 0.0
    surf_voirie = r["voirie"].area if r.get("voirie") else 0.0
    # emprises impermeables = bati + poche + voirie ; le reste = espaces verts/libres
    surf_verts = max(0.0, surf_parcelle - surf_bati - surf_poche - surf_voirie)
    stationne = min(n_gar, n_pl)
    emprise_pct = (surf_bati / surf_parcelle * 100) if surf_parcelle else 0
    verts_pct = (surf_verts / surf_parcelle * 100) if surf_parcelle else 0
    ces_max = p.get("ces_max", 1.0) * 100
    ev_min = p.get("espaces_verts_min", 0.0) * 100
    return {
        "surface_parcelle_m2": round(surf_parcelle, 1),
        "surface_batie_m2": round(surf_bati, 1),
        "surface_espaces_verts_m2": round(surf_verts, 1),
        "surface_poche_stationnement_m2": round(surf_poche, 1),
        "surface_voirie_m2": round(surf_voirie, 1),
        "nb_logements": n_log,
        "nb_places": n_pl,
        "nb_garages": n_gar,
        "emprise_au_sol_pct": round(emprise_pct, 1),
        "espaces_verts_pct": round(verts_pct, 1),
        "ces_respecte": emprise_pct <= ces_max + 0.1,
        "espaces_verts_respecte": verts_pct >= ev_min - 0.1,
        "stationnement_suffisant": stationne >= n_log,
        "logements_non_stationnes": max(0, n_log - stationne),
    }
