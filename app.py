import streamlit as st
import script_web
import gmb
import update_summary
from datetime import datetime

# ----------------------------------------------------------
# État global
# ----------------------------------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

if "busy" not in st.session_state:
    st.session_state.busy = False

if "logs" not in st.session_state:
    st.session_state.logs = []

# ----------------------------------------------------------
# Liste des écoles
# ----------------------------------------------------------
ECOLES = [
    "TOUTES",
    "BRASSART",
    "CREAD",
    "EFAP",
    "EFJ",
    "ESEC",
    "ICART",
    "Ecole bleue",
]
selected = st.selectbox("Sélectionne une école :", ECOLES)

# ----------------------------------------------------------
# Logs helpers
# ----------------------------------------------------------
def add_log(msg: str):
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": str(msg)
    })

def render_logs():
    if not st.session_state.logs:
        st.info("Aucun log pour le moment.")
        return
    bullets = [f"- `{row['ts']}` {row['msg']}" for row in st.session_state.logs]
    st.markdown("\n".join(bullets))

# ----------------------------------------------------------
# Wrapper d'exécution (antidoublon + UI propre)
# ----------------------------------------------------------
def run_with_logs(func):
    # Empêche les doubles exécutions
    if st.session_state.busy:
        return

    st.session_state.busy = True
    try:
        # reset logs pour un run propre
        st.session_state.logs = []
        add_log("⏳ En cours…")

        # le logger passé aux scripts ajoute juste une ligne en mémoire
        func(lambda msg: add_log(msg))

        add_log("✅ Terminé")
    except Exception as e:
        add_log(f"❌ ERREUR : {e}")
    finally:
        st.session_state.busy = False

# ----------------------------------------------------------
# Actions sur les logs
# ----------------------------------------------------------
col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("🧹 Effacer les logs", disabled=st.session_state.busy):
        st.session_state.logs = []

with col_b:
    if st.session_state.logs:
        export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
        st.download_button(
            "⬇️ Télécharger les logs",
            data=export_txt,
            file_name="logs.txt",
            disabled=st.session_state.busy
        )

# ----------------------------------------------------------
# Boutons d'actions (un seul set, disabled pendant exécution)
# ----------------------------------------------------------
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

# ----------------------------------------------------------
# Affichage des logs (une seule fois par rerun)
# ----------------------------------------------------------
render_logs()
