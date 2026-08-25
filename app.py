"""
Generateur Plan Masse - Carre de l'Habitat
Appli web (Streamlit) autour du moteur geometrique Python.

Deux facons de definir la parcelle :
  - "Dessiner sur un plan" : on importe un plan (cadastre), on clique les
    sommets par-dessus, et on regle l'echelle (largeur reelle du plan).
  - "Terrains types / coordonnees" : presets + tableau de sommets.
"""
import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw
from shapely.geometry import Polygon, Point
from shapely.ops import nearest_points
from streamlit_image_coordinates import streamlit_image_coordinates

from engine import compute_feasibility, BUILDINGS
from render import render_plan

st.set_page_config(page_title="Plan Masse - Carre de l'Habitat", layout="wide")

PRESETS = {
    "Terrain en L (concave)": [(0, 0), (60, 0), (60, 35), (32, 35), (32, 55), (0, 55)],
    "Rectangle 50 x 40":      [(0, 0), (50, 0), (50, 40), (0, 40)],
    "Terrain triangulaire":   [(0, 0), (70, 0), (0, 50)],
    "Trapeze":                [(0, 0), (65, 0), (50, 45), (10, 45)],
}
DW = 700  # largeur d'affichage du plan a dessiner (pixels)

for k, v in {"parcel_df": pd.DataFrame(PRESETS["Terrain en L (concave)"], columns=["x", "y"]),
             "draw_points": [], "access_px": None, "calib_pts": [],
             "last_click": None, "ax": 30.0, "ay": 0.0}.items():
    st.session_state.setdefault(k, v)

# ------------------------------------------------------------------
st.sidebar.title("Parametres")
mode = st.sidebar.radio("Definir la parcelle",
                        ["Dessiner sur un plan", "Terrains types / coordonnees"])

parcel_xy, access_pt = None, None

# ==================================================================
# MODE 1 : DESSIN SUR UN PLAN DE FOND
# ==================================================================
if mode == "Dessiner sur un plan":
    st.title("Generateur de faisabilite - Carre de l'Habitat")
    st.subheader("1. Dessiner sur votre plan")

    up = st.file_uploader("Importer un plan de fond (cadastre) - PNG ou JPG",
                          type=["png", "jpg", "jpeg"])
    if up is None:
        st.info("Importez un plan, puis : (1) calibrez l'echelle avec 2 points de "
                "distance connue, (2) cliquez les sommets de la parcelle, (3) placez l'acces.")
        st.stop()

    action = st.radio("Le clic sert a :",
                      ["Sommet de la parcelle", "Placer l'acces voiture", "Point de calibrage"],
                      horizontal=True)

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Annuler dernier sommet") and st.session_state.draw_points:
        st.session_state.draw_points.pop()
    if b2.button("Effacer parcelle"):
        st.session_state.draw_points = []
    if b3.button("Effacer calibrage"):
        st.session_state.calib_pts = []
    ferme = b4.checkbox("Fermer la parcelle", value=True)

    # --- echelle : calibrage par 2 points (ideal pour un plan 1:500) ---------
    st.markdown("**Echelle** — placez 2 points de distance connue (ex. un cote de "
                "parcelle cote, une barre d'echelle), puis saisissez la distance reelle.")
    calib = st.session_state.calib_pts
    dist_reelle = st.number_input("Distance reelle entre les 2 points de calibrage (metres)",
                                  min_value=0.1, value=20.0, step=0.5)
    img = Image.open(up).convert("RGB")
    dh = int(img.height * DW / img.width)
    base = img.resize((DW, dh))

    mpp = None
    if len(calib) == 2:
        pix = ((calib[0][0] - calib[1][0]) ** 2 + (calib[0][1] - calib[1][1]) ** 2) ** 0.5
        if pix > 1:
            mpp = dist_reelle / pix
            st.success(f"Echelle calibree : 1 pixel = {mpp:.3f} m  "
                       f"(le plan affiche fait {DW*mpp:.1f} m de large).")
    if mpp is None:
        st.warning("Echelle non calibree : placez 2 points de calibrage. "
                   "En attendant, une echelle par defaut est utilisee.")
        mpp = 20.0 / DW  # defaut neutre

    # --- overlay : parcelle + acces + calibrage ------------------------------
    disp = base.copy()
    d = ImageDraw.Draw(disp)
    pts = st.session_state.draw_points
    if len(pts) >= 2:
        d.line(pts + ([pts[0]] if ferme and len(pts) >= 3 else []), fill=(230, 80, 30), width=3)
    for (px, py) in pts:
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(230, 80, 30), outline="white")
    if len(calib) >= 1:
        if len(calib) == 2:
            d.line(calib, fill=(20, 130, 200), width=3)
        for (px, py) in calib:
            d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(20, 130, 200), outline="white")
    if st.session_state.access_px is not None:
        px, py = st.session_state.access_px
        d.polygon([(px, py - 9), (px - 8, py + 7), (px + 8, py + 7)],
                  fill=(230, 140, 0), outline="white")

    st.caption("Cliquez sur le plan selon l'action choisie ci-dessus.")
    val = streamlit_image_coordinates(disp, key="cadastre")
    if val is not None:
        click = (int(val["x"]), int(val["y"]))
        if click != st.session_state.last_click:
            st.session_state.last_click = click
            if action == "Sommet de la parcelle":
                st.session_state.draw_points.append(click)
            elif action == "Placer l'acces voiture":
                st.session_state.access_px = click
            else:
                if len(st.session_state.calib_pts) >= 2:
                    st.session_state.calib_pts = []
                st.session_state.calib_pts.append(click)
            st.rerun()

    if len(pts) < 3:
        st.info(f"{len(pts)} sommet(s) pose(s). Il en faut au moins 3.")
        st.stop()

    # conversion pixels -> metres (Y inverse : haut de l'image = Y grand)
    to_m = lambda px, py: (px * mpp, (dh - py) * mpp)
    parcel_xy = [to_m(px, py) for (px, py) in pts]

    if st.session_state.access_px is not None:
        access_pt = to_m(*st.session_state.access_px)
        st.caption("Acces : place manuellement (repere orange).")
    else:
        a, b = parcel_xy[0], parcel_xy[1]
        access_pt = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        st.caption("Acces : non place -> milieu du 1er cote par defaut "
                   "(choisis 'Placer l'acces voiture' et clique pour le definir).")

# ==================================================================
# MODE 2 : PRESETS / COORDONNEES
# ==================================================================
else:
    st.title("Generateur de faisabilite - Carre de l'Habitat")
    st.sidebar.subheader("1. Parcelle")
    preset = st.sidebar.selectbox("Charger un terrain type", list(PRESETS.keys()))
    if st.sidebar.button("Charger ce terrain"):
        st.session_state.parcel_df = pd.DataFrame(PRESETS[preset], columns=["x", "y"])

    st.sidebar.caption("Sommets de la parcelle, en metres (X = est, Y = nord). "
                       "Une ligne = un sommet, dans l'ordre du contour.")
    df = st.sidebar.data_editor(
        st.session_state.parcel_df, num_rows="dynamic", width="stretch", key="editor",
        column_config={"x": st.column_config.NumberColumn("X (m)"),
                       "y": st.column_config.NumberColumn("Y (m)")})
    parcel_xy = [(float(r.x), float(r.y)) for r in df.itertuples()]

    st.sidebar.subheader("2. Point d'acces sur rue")
    c1, c2 = st.sidebar.columns(2)
    axv = c1.number_input("Acces X", value=float(st.session_state.ax))
    ayv = c2.number_input("Acces Y", value=float(st.session_state.ay))
    if len(parcel_xy) >= 3:
        try:
            poly = Polygon(parcel_xy)
            snap = nearest_points(poly.exterior, Point(axv, ayv))[0]
            access_pt = (snap.x, snap.y)
        except Exception:
            access_pt = None
    st.sidebar.caption("Le point sera projete sur le bord le plus proche.")

# ==================================================================
# REGLES + BATIMENTS (communs aux deux modes)
# ==================================================================
st.sidebar.subheader("3. Regles d'urbanisme")
retrait = st.sidebar.slider("Retrait limites separatives (m)", 0.0, 15.0, 4.0, 0.5)
dist_inter = st.sidebar.slider("Distance min entre batiments (m)", 0.0, 15.0, 5.0, 0.5)

st.sidebar.subheader("4. Batiments autorises")
enabled = [n for n in BUILDINGS if st.sidebar.checkbox(
    f"{n} ({BUILDINGS[n]['log']} lgt - {BUILDINGS[n]['w']}x{BUILDINGS[n]['h']}m)", value=True)]

# ==================================================================
# CALCUL + AFFICHAGE
# ==================================================================
valid = parcel_xy is not None and len(parcel_xy) >= 3
if valid:
    try:
        Polygon(parcel_xy)
    except Exception:
        valid = False
if not valid:
    st.warning("Definis au moins 3 sommets valides pour la parcelle.")
    st.stop()
if not enabled:
    st.warning("Coche au moins un type de batiment.")
    st.stop()
if access_pt is None:
    access_pt = list(Polygon(parcel_xy).centroid.coords)[0]

result = compute_feasibility(parcel_xy, access_pt,
                             {"retrait_sep": retrait, "dist_inter": dist_inter, "enabled": enabled})
k = result["kpis"]

st.subheader("Resultat" if mode == "Dessiner sur un plan" else "")
col_plan, col_kpi = st.columns([3, 2])
with col_plan:
    st.pyplot(render_plan(result, parcel_xy, access_pt))
with col_kpi:
    if result["message"]:
        st.error(result["message"])
    if not k.get("stationnement_suffisant", True):
        st.warning(f"Stationnement insuffisant : {k['logements_non_stationnes']} "
                   f"logement(s) non stationne(s). La forme du terrain limite les emplacements.")
    st.subheader("Indicateurs")
    a, b = st.columns(2)
    a.metric("Logements", k["nb_logements"])
    b.metric("Places / Garages", f'{k["nb_places"]} / {k["nb_garages"]}')
    a.metric("Surface parcelle", f'{k["surface_parcelle_m2"]:.0f} m2')
    b.metric("Surface batie", f'{k["surface_batie_m2"]:.0f} m2')
    a.metric("Espace libre", f'{k["surface_libre_m2"]:.0f} m2')
    b.metric("Poche stationnement", f'{k["surface_poche_stationnement_m2"]:.0f} m2')
    emprise = (k["surface_batie_m2"] / k["surface_parcelle_m2"] * 100) if k["surface_parcelle_m2"] else 0
    st.metric("Emprise au sol", f"{emprise:.1f} %")

st.caption("Moteur v1 - zone constructible robuste, stationnement 1:1:1 verifie, "
           "cheminements pietons vers la coursive de chaque batiment.")
