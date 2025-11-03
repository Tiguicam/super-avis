# app.py
import streamlit as st
from datetime import datetime

import script_web
import gmb
import update_summary

# --- UI de base ---
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

# --- State ---
if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []
if "log_msgs" not in st.session_state:
    # set() des messages déjà vus → empêche les doublons visuels quand Streamlit rerun
    st.session_state.log_msgs = set()

# --- Sélecteur d’école ---
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
selected = st.selectbox("Sélectionne une école :", ECOLES)

# --- Zone d’affichage des logs ---
logs_box = st.container()

def render_logs():
    if not st.session_state.logs:
        logs_box.info("Aucun log pour le moment.")
        return
    bullets = [f"- `{row['ts']}` {row['msg']}" for row in st.session_state.logs]
    logs_box.markdown("\n".join(bullets))

def _append_log(msg: str):
    """Ajoute un log seulement si le message n'a pas déjà été affiché (anti-doublon)."""
    msg = str(msg)

    # filtrage : on ignore les logs techniques inutiles
    skip = [
        "Filtre école",
        "Collecte pour",
        "Web scraping terminé",
    ]
    if any(s in msg for s in skip):
        return

    # anti-doublon basé sur contenu
    if msg in st.session_state.log_msgs:
        return

    # on mémorise le contenu unique ici
    st.session_state.log_msgs.add(msg)

    # on affiche avec timestamp
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": msg
    })
    render_logs()


def run_with_logs(func):
    """Exécute une action en affichant des logs simples, sans doublons."""
    if st.session_state.busy:
        return
    st.session_state.busy = True

    # reset des logs à chaque run
    st.session_state.logs = []
    st.session_state.log_msgs = set()
    render_logs()

    try:
        _append_log("⏳ En cours…")
        # on passe notre logger anti-doublon au script appelé
        func(lambda m: _append_log(m))
        _append_log("✅ Terminé")
    except Exception as e:
        _append_log(f"❌ ERREUR : {e}")
    finally:
        st.session_state.busy = False

# --- Barre d’actions (haut) ---
col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("🧹 Effacer les logs", disabled=st.session_state.busy):
        st.session_state.logs = []
        st.session_state.log_msgs = set()
        render_logs()
with col_b:
    if st.session_state.logs:
        export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
        st.download_button("⬇️ Télécharger les logs", data=export_txt, file_name="logs.txt",
                           disabled=st.session_state.busy)

# Affichage initial
render_logs()

# --- Boutons d’actions (bas) ---
col1, col2, col3 = st.columns(3)

with col1:
    st.button(
        "Scraper plateformes web",
        disabled=st.session_state.busy,
        on_click=lambda: run_with_logs(
            lambda logger: script_web.run(logger=logger, school_filter=selected)
        )
    )

with col2:
    st.button(
        "Avis Google Business",
        disabled=st.session_state.busy,
        on_click=lambda: run_with_logs(
            lambda logger: gmb.run(logger=logger, school_filter=selected)
        )
    )

with col3:
    st.button(
        "Mettre à jour le Sommaire",
        disabled=st.session_state.busy,
        on_click=lambda: run_with_logs(
            lambda logger: update_summary.run(logger=logger, school_filter=selected)
        )
    )
