import streamlit as st
import time
from datetime import datetime

import script_web
import gmb
import update_summary

# ------------------------------ INIT ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

# État persistant
if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []           # liste affichée
if "seen_msgs" not in st.session_state:
    st.session_state.seen_msgs = set()   # anti-doublon global (ne se réinitialise pas)
if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"

# ------------------------------ ECOLES ------------------------------
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school),
    disabled=st.session_state.busy,   # évite les reruns pendant l’exécution
)

# ------------------------------ LOGS UI ------------------------------
logs_box = st.container()

def render_logs():
    if not st.session_state.logs:
        logs_box.info("Aucun log pour le moment.")
        return
    txt = "\n".join(f"- `{r['ts']}` {r['msg']}" for r in st.session_state.logs)
    logs_box.markdown(txt)

def append_log(msg: str):
    """Ajoute un log SI et seulement si on ne l’a jamais vu (anti-doublon global)."""
    msg = (msg or "").strip()
    if not msg:
        return
    if msg in st.session_state.seen_msgs:
        return
    st.session_state.seen_msgs.add(msg)
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
    })
    render_logs()
    time.sleep(0.01)  # petit yield pour pousser l'UI

render_logs()

# ------------------------------ RUNNER SYNCHRONE ------------------------------
def run_sync(task: str, school: str):
    """Exécute en synchrone et ‘stream’ les logs au fil de l’eau, sans doublons."""
    if st.session_state.busy:
        return
    st.session_state.busy = True

    # Ligne de séparation pour visualiser les runs successifs (n'efface rien)
    sep = f"— RUN {datetime.now().strftime('%H:%M:%S')} • {task.upper()} • {school} —"
    append_log(sep)
    append_log("⏳ En cours…")

    def logger(m):
        append_log(str(m))

    try:
        if task == "web":
            script_web.run(logger=logger, school_filter=school)
        elif task == "gmb":
            gmb.run(logger=logger, school_filter=school)
        elif task == "summary":
            update_summary.run(logger=logger, school_filter=school)
        append_log("✅ Terminé")
    except Exception as e:
        append_log(f"❌ ERREUR : {e}")
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
        on_click=lambda: (st.session_state.logs.clear(), render_logs()),
    )

# ------------------------------ EXPORT ------------------------------
if st.session_state.logs:
    export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
    st.download_button(
        "⬇️ Télécharger les logs",
        data=export_txt,
        file_name="logs.txt",
        disabled=st.session_state.busy,
    )
