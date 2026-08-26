"""
Cheminements pietons - reseau ORTHOGONAL aligne sur l'orientation des batiments.

Principes (faisabilite Carre de l'Habitat) :
- l'entree d'un batiment se fait au MILIEU d'une facade (celle tournee vers l'allee) ;
- les cheminements suivent l'orientation generale des batiments (repere pivote +
  deplacements orthogonaux) pour garder l'unite du plan ;
- ils laissent une marge (jardins) autour des batiments et evitent totalement les
  stationnements ;
- ils partent de l'allee de la poche de stationnement.
"""
import heapq
import math
from shapely.geometry import LineString, Point
from shapely.affinity import rotate
from shapely.ops import unary_union


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


def _mid_facade(bounds, alley):
    """Milieu de la facade (parmi les 4) la plus proche de l'allee."""
    minx, miny, maxx, maxy = bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    mids = [(cx, miny), (cx, maxy), (minx, cy), (maxx, cy)]
    return min(mids, key=lambda m: (m[0] - alley[0]) ** 2 + (m[1] - alley[1]) ** 2)


def _astar(walkable, ncols, nrows, start, goal):
    """A* 4-directions (orthogonal) -> cheminements alignes sur la trame."""
    h = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1])
    openq = [(h(start, goal), 0.0, start)]
    came, gsc = {}, {start: 0.0}
    nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    while openq:
        _, g, cur = heapq.heappop(openq)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        for di, dj in nbrs:
            ni, nj = cur[0] + di, cur[1] + dj
            if not (0 <= ni < ncols and 0 <= nj < nrows) or not walkable[ni][nj]:
                continue
            ng = g + 1.0
            nn = (ni, nj)
            if ng < gsc.get(nn, 1e18):
                gsc[nn] = ng
                came[nn] = cur
                heapq.heappush(openq, (ng + h(nn, goal), ng, nn))
    return None


def find_paths(zone, buildings, bay, stalls=None, angle_deg=0.0, dist_inter=5.0, step=None):
    corridors = [central_axis(b[1]) for b in buildings]
    if bay is None or not buildings:
        return corridors, []
    stalls = stalls or []

    origin = zone.centroid.coords[0]
    R = lambda g: rotate(g, -angle_deg, origin=origin)     # vers repere aligne
    Rb = lambda g: rotate(g, angle_deg, origin=origin)     # retour repere reel

    zone_r, bay_r = R(zone), R(bay)
    blds_r = [R(b[1]) for b in buildings]
    stalls_r = [R(s) for _, s in stalls]

    free = zone_r.union(bay_r)
    minx, miny, maxx, maxy = free.bounds
    if step is None:
        step = max(1.5, max(maxx - minx, maxy - miny) / 55.0)
    ncols = max(2, int((maxx - minx) / step) + 1)
    nrows = max(2, int((maxy - miny) / step) + 1)

    garden = min(2.0, dist_inter * 0.35)                   # marge jardins
    obs = [b.buffer(garden) for b in blds_r] + [s.buffer(0.20) for s in stalls_r]
    obstacles = unary_union(obs) if obs else None

    cell_xy = lambda i, j: (minx + i * step, miny + j * step)
    walkable = [[False] * nrows for _ in range(ncols)]
    for i in range(ncols):
        for j in range(nrows):
            pt = Point(cell_xy(i, j))
            walkable[i][j] = free.contains(pt) and not (obstacles and obstacles.contains(pt))

    def nearest_cell(pt):
        best, bd = None, 1e18
        for i in range(ncols):
            for j in range(nrows):
                if walkable[i][j]:
                    dd = (cell_xy(i, j)[0] - pt[0]) ** 2 + (cell_xy(i, j)[1] - pt[1]) ** 2
                    if dd < bd:
                        bd, best = dd, (i, j)
        return best

    if stalls_r:
        alley_region = bay_r.difference(unary_union(stalls_r).buffer(0.20))
    else:
        alley_region = bay_r
    alley = (alley_region.representative_point().coords[0]
             if not alley_region.is_empty else bay_r.centroid.coords[0])
    start = nearest_cell(alley)

    paths = []
    for b_r in blds_r:
        entrance = _mid_facade(b_r.bounds, alley)           # milieu de facade
        goal = nearest_cell(entrance)
        if start is None or goal is None:
            continue
        cells = _astar(walkable, ncols, nrows, start, goal)
        if cells:
            pts = [alley] + [cell_xy(i, j) for i, j in cells] + [entrance]
            line_r = LineString(pts).simplify(step * 0.2)
            paths.append(Rb(line_r))                         # retour repere reel
    return corridors, paths
