"""
Generateur Plan Masse - Carre de l'Habitat
Appli web (Streamlit) autour du moteur generatif.

Deux facons de definir la parcelle :
  - "Dessiner sur un plan" : import PDF (cadastre) ou image, on CALIBRE par une
    cote de reference (2 points + longueur reelle -> seule source de verite pour
    l'echelle), puis on clique la parcelle et l'acces.
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
    "Terrain allonge":        [(0, 0), (15, -25), (120, -10), (130, 30), (60, 40), (10, 30)],
    "Trapeze":                [(0, 0), (65, 0), (50, 45), (10, 45)],
}
DW = 820          # largeur d'affichage du plan (pixels)
DPI = 150         # rendu des PDF

for key, val in {"parcel_df": pd.DataFrame(PRESETS["Terrain en L (concave)"], columns=["x", "y"]),
                 "draw_points": [], "access_px": None, "calib_pts": [],
                 "last_click": None}.items():
    st.session_state.setdefault(key, val)


def load_background(upload):
    """PDF ou image -> image PIL redimensionnee a DW de large (+ hauteur)."""
    if upload.name.lower().endswith(".pdf"):
        import pymupdf
        doc = pymupdf.open(stream=upload.getvalue(), filetype="pdf")
        pxm = doc[0].get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pxm.width, pxm.height), pxm.samples)
    else:
        img = Image.open(upload).convert("RGB")
    dh = int(img.height * DW / img.width)
    return img.resize((DW, dh)), dh


# ==================================================================
st.sidebar.title("Parametres")
mode = st.sidebar.radio("Definir la parcelle",
                        ["Dessiner sur un plan", "Terrains types / coordonnees"])
parcel_xy, access_pt = None, None

# ------------------------------------------------------------------
# MODE 1 : DESSIN SUR PLAN (calibrage "cote de reference")
# ------------------------------------------------------------------
if mode == "Dessiner sur un plan":
    st.title("Generateur de faisabilite - Carre de l'Habitat")

    up = st.file_uploader("Importer votre plan - PDF (cadastre) ou image PNG/JPG",
                          type=["pdf", "png", "jpg", "jpeg"])
    if up is None:
        st.info("Etapes : 1) importer le plan  2) calibrer avec une cote de reference "
                "(2 points + longueur reelle)  3) cliquer les sommets de la parcelle  "
                "4) placer l'acces voiture.")
        st.stop()

    base, dh = load_background(up)

    st.subheader("1. Calibrage - cote de reference")
    st.caption("Choisissez 'Cote de reference' puis cliquez 2 points d'une longueur "
               "connue (une limite parcellaire cotee, deux croix du quadrillage...). "
               "L'echelle en decoule, au cm pres.")

    action = st.radio("Le clic sert a :",
                      ["Cote de reference (2 points)", "Sommet de la parcelle",
                       "Placer l'acces voiture"], horizontal=True)

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Annuler dernier sommet") and st.session_state.draw_points:
        st.session_state.draw_points.pop()
    if c2.button("Effacer parcelle"):
        st.session_state.draw_points = []
    if c3.button("Effacer calibrage"):
        st.session_state.calib_pts = []
    ferme = c4.checkbox("Fermer la parcelle", value=True)

    calib = st.session_state.calib_pts
    mpp = None
    if len(calib) == 2:
        longueur = st.number_input("Longueur reelle de ce segment (metres)",
                                   min_value=0.10, value=20.0, step=0.10, format="%.2f")
        pixd = ((calib[0][0] - calib[1][0]) ** 2 + (calib[0][1] - calib[1][1]) ** 2) ** 0.5
        if pixd > 1:
            mpp = longueur / pixd
            st.success(f"Echelle verrouillee : 1 px = {mpp:.4f} m "
                       f"(plan affiche = {DW * mpp:.1f} m de large).")
    else:
        st.warning(f"{len(calib)}/2 point(s) de calibrage. Placez la cote de reference "
                   f"pour verrouiller l'echelle avant de dessiner.")

    # ---- overlay (calibrage bleu, parcelle orange, acces triangle) ----
    disp = base.copy()
    d = ImageDraw.Draw(disp)
    pts = st.session_state.draw_points
    if len(pts) >= 2:
        d.line(pts + ([pts[0]] if ferme and len(pts) >= 3 else []), fill=(230, 80, 30), width=3)
    for (px, py) in pts:
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(230, 80, 30), outline="white")
    if len(calib) >= 1:
        if len(calib) == 2:
            d.line(calib, fill=(20, 130, 200), width=4)
        for (px, py) in calib:
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(20, 130, 200), outline="white")
    if st.session_state.access_px is not None:
        px, py = st.session_state.access_px
        d.polygon([(px, py - 10), (px - 9, py + 8), (px + 9, py + 8)],
                  fill=(230, 140, 0), outline="white")

    val = streamlit_image_coordinates(disp, key="plan")
    if val is not None:
        click = (int(val["x"]), int(val["y"]))
        if click != st.session_state.last_click:
            st.session_state.last_click = click
            if action == "Cote de reference (2 points)":
                if len(st.session_state.calib_pts) >= 2:
                    st.session_state.calib_pts = []
                st.session_state.calib_pts.append(click)
            elif action == "Sommet de la parcelle":
                st.session_state.draw_points.append(click)
            else:
                st.session_state.access_px = click
            st.rerun()

    if mpp is None:
        st.stop()
    if len(pts) < 3:
        st.subheader("2. Dessiner la parcelle")
        st.info(f"{len(pts)} sommet(s). Cliquez au moins 3 sommets (action "
                f"'Sommet de la parcelle').")
        st.stop()

    # pixels -> metres (Y inverse : haut image = Y grand)
    to_m = lambda px, py: (px * mpp, (dh - py) * mpp)
    parcel_xy = [to_m(px, py) for (px, py) in pts]
    if st.session_state.access_px is not None:
        access_pt = to_m(*st.session_state.access_px)
    else:
        a, b = parcel_xy[0], parcel_xy[1]
        access_pt = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        st.caption("Acces non place : milieu du 1er cote par defaut "
                   "(action 'Placer l'acces voiture' pour le definir).")

# ------------------------------------------------------------------
# MODE 2 : PRESETS / COORDONNEES
# ------------------------------------------------------------------
else:
    st.title("Generateur de faisabilite - Carre de l'Habitat")
    st.sidebar.subheader("1. Parcelle")
    preset = st.sidebar.selectbox("Charger un terrain type", list(PRESETS.keys()))
    if st.sidebar.button("Charger ce terrain"):
        st.session_state.parcel_df = pd.DataFrame(PRESETS[preset], columns=["x", "y"])
    st.sidebar.caption("Sommets en metres (X = est, Y = nord), dans l'ordre du contour.")
    df = st.sidebar.data_editor(
        st.session_state.parcel_df, num_rows="dynamic", width="stretch", key="editor",
        column_config={"x": st.column_config.NumberColumn("X (m)"),
                       "y": st.column_config.NumberColumn("Y (m)")})
    parcel_xy = [(float(row.x), float(row.y)) for row in df.itertuples()]
    st.sidebar.subheader("2. Point d'acces sur rue")
    cc1, cc2 = st.sidebar.columns(2)
    axv = cc1.number_input("Acces X", value=30.0)
    ayv = cc2.number_input("Acces Y", value=0.0)
    if len(parcel_xy) >= 3:
        try:
            snap = nearest_points(Polygon(parcel_xy).exterior, Point(axv, ayv))[0]
            access_pt = (snap.x, snap.y)
        except Exception:
            access_pt = None

# ==================================================================
# REGLES PLU + PRODUITS (communs)
# ==================================================================
st.sidebar.subheader("3. Regles PLU")
retrait = st.sidebar.slider("Retrait limites separatives (m)", 0.0, 15.0, 4.0, 0.5)
retrait_voie = st.sidebar.slider("Retrait voirie / alignement (m)", 0.0, 15.0, 5.0, 0.5)
dist_inter = st.sidebar.slider("Distance entre batiments / jardins (m)", 3.0, 15.0, 6.0, 0.5)
ces_max = st.sidebar.slider("Emprise au sol max - CES (%)", 5, 100, 100, 5) / 100.0
ev_min = st.sidebar.slider("Espaces verts min (%)", 0, 80, 0, 5) / 100.0
voirie_larg = st.sidebar.slider("Largeur voirie carrossable (m)", 3.0, 8.0, 5.0, 0.5)
mail_larg = st.sidebar.slider("Largeur mail pietonnier (m)", 1.5, 6.0, 3.0, 0.5)

st.sidebar.subheader("4. Produits autorises")
enabled = [n for n in BUILDINGS if st.sidebar.checkbox(
    f"{n} ({BUILDINGS[n]['log']} lgt - {BUILDINGS[n]['w']}x{BUILDINGS[n]['h']}m)",
    value=True, key=f"bat_{n}")]
if enabled:
    st.sidebar.caption("Produits actifs : " + ", ".join(enabled))

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
    st.warning("Coche au moins un produit.")
    st.stop()
if access_pt is None:
    access_pt = list(Polygon(parcel_xy).centroid.coords)[0]

result = compute_feasibility(parcel_xy, access_pt, {
    "retrait_sep": retrait, "retrait_voie": retrait_voie, "dist_inter": dist_inter,
    "ces_max": ces_max, "espaces_verts_min": ev_min, "voirie_larg": voirie_larg,
    "mail_larg": mail_larg, "enabled": enabled})
k = result["kpis"]

st.subheader("Plan-masse")
col_plan, col_kpi = st.columns([3, 2])
with col_plan:
    st.pyplot(render_plan(result, parcel_xy, access_pt))
with col_kpi:
    if result["message"]:
        st.error(result["message"])
    if not k.get("stationnement_suffisant", True):
        st.warning(f"Stationnement insuffisant : {k['logements_non_stationnes']} lgt non stationne(s).")
    if not k.get("ces_respecte", True):
        st.warning(f"CES depasse : emprise {k['emprise_au_sol_pct']} %.")
    if not k.get("espaces_verts_respecte", True):
        st.warning(f"Espaces verts insuffisants : {k['espaces_verts_pct']} %.")
    st.subheader("Indicateurs")
    a, b = st.columns(2)
    a.metric("Logements", k["nb_logements"])
    b.metric("Places / Garages", f'{k["nb_places"]} / {k["nb_garages"]}')
    a.metric("Surface parcelle", f'{k["surface_parcelle_m2"]:.0f} m2')
    b.metric("Surface batie", f'{k["surface_batie_m2"]:.0f} m2')
    a.metric("Emprise au sol", f'{k["emprise_au_sol_pct"]:.1f} %')
    b.metric("Espaces verts", f'{k["espaces_verts_pct"]:.1f} %')
    a.metric("Voirie (ml)", f'{k["ml_voirie"]:.0f} m')
    b.metric("VRD / logement", f'{k["ratio_vrd_par_logement_m2"]:.0f} m2')

st.caption("Moteur generatif - acces -> poche groupee -> mail central -> rangees de "
           "produits standard se faisant face. VRD minimise. Echelle par cote de reference.")
