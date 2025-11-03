import streamlit as st
import time
from datetime import datetime

import script_web
import gmb
import update_summary

# ------------------------------ INIT ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []
if "log_msgs" not in st.session_state:
    st.session_state.log_msgs = set()
if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"

# ------------------------------ ECOLES ------------------------------
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school),
    disabled=st.session_state.busy,  # évite de relancer un rerun pendant exécution
)

# ------------------------------ LOG UI ------------------------------
logs_box = st.container()

def _render_logs():
    if not st.session_state.logs:
        logs_box.info("Aucun log pour le moment.")
        return
    txt = "\n".join(f"- `{r['ts']}` {r['msg']}" for r in st.session_state.logs)
    logs_box.markdown(txt)

def _append_log(msg: str):
    msg = str(msg).strip()
    if not msg:
        return
    # Anti-doublon strict : si le même message exact existe déjà, on ignore
    if msg in st.session_state.log_msgs:
        return
    st.session_state.log_msgs.add(msg)
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
    })
    _render_logs()
    # petit yield pour laisser Streamlit pousser l'UI
    time.sleep(0.01)

_render_logs()

# ------------------------------ RUN WRAPPER (synchrone) ------------------------------
def run_sync(task: str, school: str):
    """Exécute la tâche en synchrone et stream les logs au fil de l'eau."""
    if st.session_state.busy:
        return
    st.session_state.busy = True

    # Reset seulement au démarrage d'un run (pas quand tu changes d'école)
    st.session_state.logs = []
    st.session_state.log_msgs = set()
    _render_logs()

    def logger(m):
        _append_log(m)

    try:
        _append_log("⏳ En cours…")
        if task == "web":
            script_web.run(logger=logger, school_filter=school)
        elif task == "gmb":
            gmb.run(logger=logger, school_filter=school)
        elif task == "summary":
            update_summary.run(logger=logger, school_filter=school)
        _append_log("✅ Terminé")
    except Exception as e:
        _append_log(f"❌ ERREUR : {e}")
    finally:
        st.session_state.busy = False

# ------------------------------ BOUTONS ------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.button(
        "Scraper plateformes web",
        disabled=st.session_state.busy,
        on_click=lambda: run_sync("web", st.session_state.selected_school),
    )

with col2:
    st.button(
        "Avis Google Business",
        disabled=st.session_state.busy,
        on_click=lambda: run_sync("gmb", st.session_state.selected_school),
    )

with col3:
    st.button(
        "Mettre à jour le Sommaire",
        disabled=st.session_state.busy,
        on_click=lambda: run_sync("summary", st.session_state.selected_school),
    )

with col4:
    st.button(
        "🧹 Effacer les logs",
        disabled=st.session_state.busy,
        on_click=lambda: (st.session_state.logs.clear(), st.session_state.log_msgs.clear(), _render_logs()),
    )

# bouton de téléchargement
if st.session_state.logs:
    export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
    st.download_button(
        "⬇️ Télécharger les logs",
        data=export_txt,
        file_name="logs.txt",
        disabled=st.session_state.busy,
    )
