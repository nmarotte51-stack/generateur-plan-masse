"""
Generateur Plan Masse - Carre de l'Habitat
Appli web (Streamlit) autour du moteur geometrique Python.

Lancement local (optionnel) :  streamlit run app.py
En ligne : voir la notice de deploiement (gratuit, sans installation).
"""
import streamlit as st
import pandas as pd
from shapely.geometry import Polygon, Point
from shapely.ops import nearest_points

from engine import compute_feasibility, BUILDINGS
from render import render_plan

st.set_page_config(page_title="Plan Masse - Carre de l'Habitat", layout="wide")

# ------------------------------------------------------------------
# Parcelles de depart (presets) - coordonnees en metres
# ------------------------------------------------------------------
PRESETS = {
    "Terrain en L (concave)": [(0, 0), (60, 0), (60, 35), (32, 35), (32, 55), (0, 55)],
    "Rectangle 50 x 40":      [(0, 0), (50, 0), (50, 40), (0, 40)],
    "Terrain triangulaire":   [(0, 0), (70, 0), (0, 50)],
    "Trapaze":                [(0, 0), (65, 0), (50, 45), (10, 45)],
}

if "parcel_df" not in st.session_state:
    coords = PRESETS["Terrain en L (concave)"]
    st.session_state.parcel_df = pd.DataFrame(coords, columns=["x", "y"])
    st.session_state.ax, st.session_state.ay = 30.0, 0.0

# ------------------------------------------------------------------
# BARRE LATERALE - parametres
# ------------------------------------------------------------------
st.sidebar.title("Parametres")

st.sidebar.subheader("1. Parcelle")
preset = st.sidebar.selectbox("Charger un terrain type", list(PRESETS.keys()))
if st.sidebar.button("Charger ce terrain"):
    st.session_state.parcel_df = pd.DataFrame(PRESETS[preset], columns=["x", "y"])

st.sidebar.caption("Sommets de la parcelle (metres). Modifiable directement :")
parcel_df = st.sidebar.data_editor(
    st.session_state.parcel_df, num_rows="dynamic", width="stretch", key="editor")

st.sidebar.subheader("2. Point d'acces sur rue")
c1, c2 = st.sidebar.columns(2)
ax_val = c1.number_input("Acces X", value=float(st.session_state.ax))
ay_val = c2.number_input("Acces Y", value=float(st.session_state.ay))
st.sidebar.caption("Le point sera projete sur le bord le plus proche de la parcelle.")

st.sidebar.subheader("3. Regles d'urbanisme")
retrait = st.sidebar.slider("Retrait limites separatives (m)", 0.0, 15.0, 4.0, 0.5)
dist_inter = st.sidebar.slider("Distance min entre batiments (m)", 0.0, 15.0, 5.0, 0.5)

st.sidebar.subheader("4. Batiments autorises")
enabled = [name for name in BUILDINGS if st.sidebar.checkbox(
    f"{name} ({BUILDINGS[name]['log']} lgt - {BUILDINGS[name]['w']}x{BUILDINGS[name]['h']}m)",
    value=True)]

# ------------------------------------------------------------------
# CALCUL
# ------------------------------------------------------------------
st.title("Generateur de faisabilite - Carre de l'Habitat")

parcel_xy = [(float(row.x), float(row.y)) for row in parcel_df.itertuples()]

valid = len(parcel_xy) >= 3
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

# projette l'acces sur le bord de la parcelle
poly = Polygon(parcel_xy)
snapped = nearest_points(poly.exterior, Point(ax_val, ay_val))[0]
access_pt = (snapped.x, snapped.y)

result = compute_feasibility(parcel_xy, access_pt,
                             {"retrait_sep": retrait, "dist_inter": dist_inter, "enabled": enabled})
k = result["kpis"]

# ------------------------------------------------------------------
# AFFICHAGE
# ------------------------------------------------------------------
col_plan, col_kpi = st.columns([3, 2])

with col_plan:
    fig = render_plan(result, parcel_xy, access_pt)
    st.pyplot(fig)

with col_kpi:
    if result["message"]:
        st.error(result["message"])
    if not k.get("stationnement_suffisant", True):
        st.warning(f"Stationnement insuffisant : {k['logements_non_stationnes']} "
                   f"logement(s) non stationne(s) dans cette poche. "
                   f"La forme du terrain limite le nombre d'emplacements.")
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
           "cheminements pietons du parking vers la coursive de chaque batiment. "
           "Placement batiments/parking : heuristique a affiner.")
