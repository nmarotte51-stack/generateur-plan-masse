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
            step = 1.4142 if di and dj else 1.0
            ng = g + step
            nn = (ni, nj)
            if ng < gsc.get(nn, 1e18):
                gsc[nn] = ng
                came[nn] = cur
                heapq.heappush(openq, (ng + h(nn, goal), ng, nn))
    return None


def find_paths(zone, buildings, bay, step=1.5):
    """Rend (corridors, chemins) :
       - corridors : la coursive centrale de chaque batiment (LineString)
       - chemins   : la poly-ligne serpentant du parking a chaque coursive."""
    corridors = [central_axis(b[1]) for b in buildings]
    if bay is None or not buildings:
        return corridors, []

    # grille sur l'emprise de la zone
    minx, miny, maxx, maxy = zone.bounds
    ncols = max(2, int((maxx - minx) / step) + 1)
    nrows = max(2, int((maxy - miny) / step) + 1)
    obstacles = unary_union([b[1].buffer(0.6) for b in buildings])  # contourne les batiments

    def cell_xy(i, j):
        return (minx + i * step, miny + j * step)

    walkable = [[False] * nrows for _ in range(ncols)]
    for i in range(ncols):
        for j in range(nrows):
            p = Point(cell_xy(i, j))
            walkable[i][j] = zone.contains(p) and not obstacles.contains(p)

    def nearest_cell(pt, allow_obstacle=False):
        best, bd = None, 1e18
        for i in range(ncols):
            for j in range(nrows):
                if not allow_obstacle and not walkable[i][j]:
                    continue
                d = math.dist(cell_xy(i, j), pt)
                if d < bd:
                    bd, best = d, (i, j)
        return best

    alley = bay.centroid.coords[0]
    start = nearest_cell(alley)

    paths = []
    for corr in corridors:
        # entree = extremite de la coursive la plus proche de l'allee
        ends = list(corr.coords)
        entry = min(ends, key=lambda e: math.dist(e, alley))
        goal = nearest_cell(entry)
        if start is None or goal is None:
            continue
        cells = _astar(walkable, ncols, nrows, start, goal)
        if cells:
            pts = [alley] + [cell_xy(i, j) for i, j in cells] + [entry]
            line = LineString(pts).simplify(step * 0.6)  # lisse un peu
            paths.append(line)
    return corridors, paths
