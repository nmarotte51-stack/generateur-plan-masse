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
from shapely.geometry import Polygon, box, Point
from shapely.affinity import rotate, translate
from shapely.ops import unary_union

# ------------------------------------------------------------------
# 1. CATALOGUE (la donnee, depuis ta spec)
# ------------------------------------------------------------------
BUILDINGS = {
    "KAIA":  {"w": 14.20, "h": 15.80, "log": 4},
    "NAIA5": {"w": 15.80, "h": 15.80, "log": 5},
    "DAIA":  {"w":  8.10, "h": 14.20, "log": 2},
    "TAIA":  {"w":  8.10, "h": 21.14, "log": 3},
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


def constructible_zone(parcel_xy, retrait_separatif):
    """LE calcul critique : la zone constructible = parcelle retrecie du
    retrait separatif. Buffer negatif robuste (join mitre)."""
    poly = Polygon(parcel_xy)
    if not poly.is_valid:
        poly = poly.buffer(0)          # repare les auto-intersections du trace
    zc = poly.buffer(-retrait_separatif, join_style=2, mitre_limit=5.0)
    return _largest(zc)


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


def place_buildings(buildable, enabled, dist_inter, angle_deg):
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
    step = 1.0
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
                y += h + dist_inter

    # repivote vers le repere reel
    return [(name, rotate(g, angle_deg, origin=(cx, cy)), log) for name, g, log in placed]


# ------------------------------------------------------------------
# 4. POCHE DE STATIONNEMENT (v1 : baie double, pres de l'acces)
# ------------------------------------------------------------------
def parking_pocket(zone, access_pt, n_log, angle_deg):
    """Baie de stationnement double : une rangee de garages + une rangee de
    places, de part et d'autre d'une allee centrale, ancree pres de l'acces
    et strictement a l'interieur de la zone constructible."""
    if n_log <= 0 or zone is None:
        return None, []

    depth = GARAGE["d"] + ALLEE + PLACE["d"]      # profondeur totale de la baie
    width = n_log * GARAGE["w"]                    # largeur (n_log emplacements / rangee)

    cx, cy = zone.centroid.x, zone.centroid.y
    # baie construite a plat, centree horizontalement sur l'acces, poussee
    # vers l'interieur de la zone
    ax = rotate(Point(access_pt), -angle_deg, origin=(cx, cy))
    zone_rot = rotate(zone, -angle_deg, origin=(cx, cy))
    zminx, zminy, zmaxx, zmaxy = zone_rot.bounds

    x0 = ax.x - width / 2
    x0 = max(zminx, min(x0, zmaxx - width))        # garde la baie dans les bornes
    # essaie de coller la baie au bord le plus proche de l'acces (haut ou bas)
    if abs(ax.y - zminy) <= abs(ax.y - zmaxy):
        y0 = zminy
    else:
        y0 = zmaxy - depth

    bay = box(x0, y0, x0 + width, y0 + depth)
    bay = bay.intersection(zone_rot)               # clip strict dans la zone
    if bay.is_empty or bay.area < 1:
        return None, []

    # dessine les emplacements (visuel + comptage) dans le repere a plat
    stalls = []
    xg = x0
    for _ in range(n_log):                          # rangee garages (bas)
        stalls.append(("garage", box(xg, y0, xg + GARAGE["w"], y0 + GARAGE["d"])))
        xg += GARAGE["w"]
    xp = x0
    yp = y0 + depth - PLACE["d"]
    for _ in range(n_log):                          # rangee places (haut)
        stalls.append(("place", box(xp, yp, xp + PLACE["w"], yp + PLACE["d"])))
        xp += PLACE["w"]

    # ne garde que les emplacements reellement dans la zone
    stalls = [(k, s) for k, s in stalls if zone_rot.contains(s.buffer(-1e-6))]

    # repivote
    bay = rotate(bay, angle_deg, origin=(cx, cy))
    stalls = [(k, rotate(s, angle_deg, origin=(cx, cy))) for k, s in stalls]
    return bay, stalls


# ------------------------------------------------------------------
# 5. PIPELINE COMPLET + boucle d'ajustement bornee
# ------------------------------------------------------------------
def compute_feasibility(parcel_xy, access_pt, params):
    p = {"retrait_sep": 3.0, "dist_inter": 4.0, "enabled": list(BUILDINGS.keys())}
    p.update(params or {})

    parcel = Polygon(parcel_xy)
    zone = constructible_zone(parcel_xy, p["retrait_sep"])
    angle = dominant_angle_deg(parcel)

    result = {"parcel": parcel, "zone": zone, "buildings": [], "parking": None,
              "stalls": [], "angle": angle, "message": None}

    if zone is None or zone.area < 1:
        result["message"] = "Terrain trop petit ou retraits trop forts (zone constructible vide)."
        result["kpis"] = _kpis(result)
        return result

    if access_pt is None:
        access_pt = list(zone.centroid.coords)[0]

    # --- Recherche du point d'equilibre batiments <-> parking -------------
    # Contrainte stricte : 1 logement = 1 place + 1 garage. La poche grandit
    # donc avec le nombre de logements, ce qui reduit la place pour batir.
    # On cherche le plus grand L tel que, en reservant le parking pour L,
    # on peut encore batir au moins L logements.
    def buildable_for(Ltarget):
        bay, _ = parking_pocket(zone, access_pt, Ltarget, angle)
        if bay is None:
            return zone, None
        area = _largest(zone.difference(bay.buffer(p["dist_inter"])))
        return (area or zone), bay

    def capacity(Ltarget):
        area, _ = buildable_for(Ltarget)
        b = place_buildings(area, p["enabled"], p["dist_inter"], angle)
        return sum(x[2] for x in b)

    L0 = capacity(0)                     # potentiel brut sans parking
    L_star = 0
    for Lt in range(L0, -1, -1):         # du max vers le bas
        if capacity(Lt) >= Lt:
            L_star = Lt
            break

    # implante pour L_star, puis dimensionne la poche au nombre reellement bati
    area, _ = buildable_for(L_star)
    buildings = place_buildings(area, p["enabled"], p["dist_inter"], angle)
    L_real = sum(b[2] for b in buildings)
    bay, stalls = parking_pocket(zone, access_pt, L_real, angle)
    if bay is not None:                  # la poche finale ne doit pas mordre un batiment
        keepout = bay.buffer(p["dist_inter"])
        buildings = [b for b in buildings if not b[1].intersects(keepout)]

    # redimensionne la poche au nombre final de logements (regle stricte 1:1:1)
    L_final = sum(b[2] for b in buildings)
    if L_final > 0:
        bay, stalls = parking_pocket(zone, access_pt, L_final, angle)

    if not buildings:
        result["message"] = "Terrain trop petit ou contraintes trop fortes (aucun batiment plaçable)."

    result.update(buildings=buildings, parking=bay, stalls=stalls)
    result["kpis"] = _kpis(result)
    return result


def _kpis(r):
    surf_parcelle = r["parcel"].area
    surf_bati = sum(b[1].area for b in r["buildings"])
    n_log = sum(b[2] for b in r["buildings"])
    n_gar = sum(1 for k, _ in r["stalls"] if k == "garage")
    n_pl = sum(1 for k, _ in r["stalls"] if k == "place")
    surf_voirie = r["parking"].area if r["parking"] else 0.0
    return {
        "surface_parcelle_m2": round(surf_parcelle, 1),
        "surface_batie_m2": round(surf_bati, 1),
        "surface_libre_m2": round(surf_parcelle - surf_bati - surf_voirie, 1),
        "surface_poche_stationnement_m2": round(surf_voirie, 1),
        "nb_logements": n_log,
        "nb_places": n_pl,
        "nb_garages": n_gar,
    }
