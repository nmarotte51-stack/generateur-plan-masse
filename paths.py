"""
Circulation du plan-masse "Carre de l'Habitat".

- central_axis      : coursive centrale (axe median) d'un batiment.
- build_circulation : a partir du mail (repere pivote) et des entrees de facade,
                      construit le MAIL pietonnier + les ANTENNES orthogonales
                      (90 deg stricts) reliant le mail a chaque facade, puis
                      rebascule le tout dans le repere reel via 'Rb'.
"""
import math
from shapely.geometry import LineString


def central_axis(poly):
    """Coursive centrale = axe median du batiment dans sa plus grande longueur."""
    r = poly.minimum_rotated_rectangle
    pts = list(r.exterior.coords)[:4]
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if math.dist(pts[0], pts[1]) >= math.dist(pts[1], pts[2]):
        a, b = mid(pts[1], pts[2]), mid(pts[3], pts[0])
    else:
        a, b = mid(pts[0], pts[1]), mid(pts[2], pts[3])
    return LineString([a, b])


def build_circulation(mail_r, entrances_r, sides, mail_y, mail_w, Rb):
    """mail_r      : polygone du mail dans le repere pivote (peut etre vide)
       entrances_r : [(ex, ey), ...] milieux de facade sur mail (repere pivote)
       sides       : [+1/-1, ...] cote du mail pour chaque batiment
       mail_y, mail_w : position et largeur du mail (repere pivote)
       Rb          : fonction de rotation inverse (repere pivote -> reel)
       Retourne (mail_world, [antennes_world])."""
    mail_world = Rb(mail_r) if (mail_r is not None and not mail_r.is_empty) else None
    stubs = []
    for (ex, ey), side in zip(entrances_r, sides):
        edge_y = mail_y + (mail_w / 2.0) * side       # bord du mail cote batiment
        seg = LineString([(ex, edge_y), (ex, ey)])    # antenne strictement orthogonale
        if seg.length > 0.01:
            stubs.append(Rb(seg))
    return mail_world, stubs
