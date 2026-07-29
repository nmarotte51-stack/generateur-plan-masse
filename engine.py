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
from paths import find_paths

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
    """Baie de stationnement en PAIRES equilibrees : chaque colonne = 1 garage
    (rangee basse) + 1 place (rangee haute) de part et d'autre d'une allee
    centrale. On ne garde une colonne que si le garage ET la place tiennent
    entierement dans la zone -> il y a toujours autant de garages que de places.
    On garde les n_log colonnes les plus proches de l'acces. S'il en manque,
    c'est signale honnetement (pas de sur-affichage)."""
    if n_log <= 0 or zone is None:
        return None, []

    gd, pd = GARAGE["d"], PLACE["d"]
    depth = gd + ALLEE + pd
    col_w = max(GARAGE["w"], PLACE["w"])

    cx, cy = zone.centroid.x, zone.centroid.y
    zone_rot = rotate(zone, -angle_deg, origin=(cx, cy))
    ax = rotate(Point(access_pt), -angle_deg, origin=(cx, cy))
    zminx, zminy, zmaxx, zmaxy = zone_rot.bounds

    # la baie s'appuie sur le bord (haut ou bas) le plus proche de l'acces
    if abs(ax.y - zminy) <= abs(ax.y - zmaxy):
        y0 = zminy
    else:
        y0 = zmaxy - depth

    # colonnes candidates sur toute la largeur ; on garde celles ou garage ET
    # place tiennent dans la zone
    cols = []
    x = zminx
    while x + col_w <= zmaxx + 1e-6:
        gar = box(x, y0, x + GARAGE["w"], y0 + gd)
        pl = box(x, y0 + depth - pd, x + PLACE["w"], y0 + depth)
        if zone_rot.contains(gar.buffer(-1e-6)) and zone_rot.contains(pl.buffer(-1e-6)):
            cols.append((x, gar, pl))
        x += col_w

    if not cols:
        return None, []

    # garde les n_log colonnes les plus proches de l'acces
    cols.sort(key=lambda c: abs((c[0] + col_w / 2) - ax.x))
    cols = cols[:n_log]
    cols.sort(key=lambda c: c[0])

    xs0 = min(c[0] for c in cols)
    xs1 = max(c[0] for c in cols) + col_w
    bay = box(xs0, y0, xs1, y0 + depth).intersection(zone_rot)

    stalls = []
    for _, gar, pl in cols:
        stalls.append(("garage", gar))
        stalls.append(("place", pl))

    # repivote vers le repere reel
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
              "stalls": [], "corridors": [], "cheminements": [], "angle": angle, "message": None}

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

    # implante les batiments pour le point d'equilibre trouve
    area, _ = buildable_for(L_star)
    buildings = place_buildings(area, p["enabled"], p["dist_inter"], angle)
    L_final = sum(b[2] for b in buildings)

    # poche equilibree dimensionnee au nombre de logements ; retire un batiment
    # seulement s'il chevauche reellement la poche
    bay, stalls = parking_pocket(zone, access_pt, L_final, angle)
    if bay is not None:
        keepout = bay.buffer(p["dist_inter"])
        buildings = [b for b in buildings if not b[1].intersects(keepout)]
        L_final = sum(b[2] for b in buildings)
        bay, stalls = parking_pocket(zone, access_pt, L_final, angle)

    if not buildings:
        result["message"] = "Terrain trop petit ou contraintes trop fortes (aucun batiment plaçable)."

    corridors, cheminements = ([], [])
    if buildings and bay is not None:
        corridors, cheminements = find_paths(zone, buildings, bay)

    result.update(buildings=buildings, parking=bay, stalls=stalls,
                  corridors=corridors, cheminements=cheminements)
    result["kpis"] = _kpis(result)
    return result


def _kpis(r):
    surf_parcelle = r["parcel"].area
    surf_bati = sum(b[1].area for b in r["buildings"])
    n_log = sum(b[2] for b in r["buildings"])
    n_gar = sum(1 for k, _ in r["stalls"] if k == "garage")
    n_pl = sum(1 for k, _ in r["stalls"] if k == "place")
    surf_voirie = r["parking"].area if r["parking"] else 0.0
    stationne = min(n_gar, n_pl)                 # logements reellement stationnes
    return {
        "surface_parcelle_m2": round(surf_parcelle, 1),
        "surface_batie_m2": round(surf_bati, 1),
        "surface_libre_m2": round(surf_parcelle - surf_bati - surf_voirie, 1),
        "surface_poche_stationnement_m2": round(surf_voirie, 1),
        "nb_logements": n_log,
        "nb_places": n_pl,
        "nb_garages": n_gar,
        "stationnement_suffisant": stationne >= n_log,
        "logements_non_stationnes": max(0, n_log - stationne),
    }
