"""
Cheminements pietons : relient l'allee de la poche de stationnement a la
coursive centrale de chaque batiment, en serpentant (recherche de chemin A*
qui contourne les batiments).
"""
import heapq
import math
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


def central_axis(poly):
    """Coursive centrale = axe median du batiment dans sa plus grande longueur."""
    r = poly.minimum_rotated_rectangle
    pts = list(r.exterior.coords)[:4]
    d01 = math.dist(pts[0], pts[1])
    d12 = math.dist(pts[1], pts[2])
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if d01 >= d12:      # cotes longs = 0-1 et 2-3
        a, b = mid(pts[1], pts[2]), mid(pts[3], pts[0])
    else:               # cotes longs = 1-2 et 3-0
        a, b = mid(pts[0], pts[1]), mid(pts[2], pts[3])
    return LineString([a, b])


def _astar(walkable, ncols, nrows, start, goal):
    """A* 8-directions sur une grille booleenne. start/goal = (i, j)."""
    def h(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
    openq = [(h(start, goal), 0.0, start)]
    came, gsc = {}, {start: 0.0}
    nbrs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
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
            if di and dj:   # diagonale interdite si elle coupe un coin d'obstacle
                if not (walkable[cur[0] + di][cur[1]] and walkable[cur[0]][cur[1] + dj]):
                    continue
            step = 1.4142 if di and dj else 1.0
            ng = g + step
            nn = (ni, nj)
            if ng < gsc.get(nn, 1e18):
                gsc[nn] = ng
                came[nn] = cur
                heapq.heappush(openq, (ng + h(nn, goal), ng, nn))
    return None


def find_paths(zone, buildings, bay, stalls=None, step=None):
    """Rend (corridors, chemins) : coursive centrale de chaque batiment, et
    poly-ligne serpentant du parking a chaque coursive, evitant batiments ET
    emplacements (garages/places) mais circulant dans l'allee."""
    corridors = [central_axis(b[1]) for b in buildings]
    if bay is None or not buildings:
        return corridors, []

    stalls = stalls or []
    free = zone.union(bay)
    minx, miny, maxx, maxy = free.bounds
    if step is None:                       # grille adaptee a la taille du terrain
        step = max(1.5, max(maxx - minx, maxy - miny) / 55.0)
    ncols = max(2, int((maxx - minx) / step) + 1)
    nrows = max(2, int((maxy - miny) / step) + 1)

    obs = [b[1].buffer(0.5) for b in buildings]
    obs += [s.buffer(0.20) for _, s in stalls]     # marge nette autour des emplacements
    obstacles = unary_union(obs) if obs else None

    def cell_xy(i, j):
        return (minx + i * step, miny + j * step)

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
                    dd = math.dist(cell_xy(i, j), pt)
                    if dd < bd:
                        bd, best = dd, (i, j)
        return best

    # depart depuis l'allee (poche moins les emplacements), pas depuis une place
    if stalls:
        alley_region = bay.difference(unary_union([s for _, s in stalls]).buffer(0.20))
    else:
        alley_region = bay
    alley = (alley_region.representative_point().coords[0]
             if not alley_region.is_empty else bay.centroid.coords[0])
    start = nearest_cell(alley)

    paths = []
    for b, corr in zip(buildings, corridors):
        door = b[1].exterior.interpolate(b[1].exterior.project(Point(alley))).coords[0]
        goal = nearest_cell(door)
        if start is None or goal is None:
            continue
        cells = _astar(walkable, ncols, nrows, start, goal)
        if cells:
            pts = [alley] + [cell_xy(i, j) for i, j in cells] + [door]
            paths.append(LineString(pts).simplify(step * 0.3))
    return corridors, paths
