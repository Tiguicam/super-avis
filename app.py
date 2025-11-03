import streamlit as st
import threading
import queue
from datetime import datetime

import script_web
import gmb
import update_summary

# ----------------------------------------------------------
# Setup de base
# ----------------------------------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

# State initial
for k, v in {
    "busy": False,
    "worker": None,
    "log_queue": None,
    "logs": [],
    "task": None,            # "web" | "gmb" | "summary"
    "selected_school": "TOUTES",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :", 
    ECOLES, 
    index=ECOLES.index(st.session_state.selected_school)
)

# ----------------------------------------------------------
# Logs
# ----------------------------------------------------------
log_area = st.empty()

def _append_log(msg: str):
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": str(msg)
    })

def _render_logs():
    if not st.session_state.logs:
        log_area.info("Aucun log pour le moment.")
        return
    txt = "\n".join(f"- `{row['ts']}` {row['msg']}" for row in st.session_state.logs)
    log_area.markdown(txt)

def _drain_queue():
    """Récupère les messages depuis la queue → logs"""
    q: queue.Queue = st.session_state.log_queue
    if not q:
        return
    try:
        while True:
            msg = q.get_nowait()
            if msg == "__DONE__":
                st.session_state.busy = False
                break
            _append_log(msg)
    except queue.Empty:
        pass

def _make_logger():
    q: queue.Queue = st.session_state.log_queue
    def logger(msg):
        q.put(str(msg))
    return logger

# ----------------------------------------------------------
# Worker (thread)
# ----------------------------------------------------------
def _worker(task: str, school: str):
    logger = _make_logger()
    try:
        logger("⏳ En cours…")
        if task == "web":
            script_web.run(logger=logger, school_filter=school)
        elif task == "gmb":
            gmb.run(logger=logger, school_filter=school)
        elif task == "summary":
            update_summary.run(logger=logger, school_filter=school)
        logger("✅ Terminé")
    except Exception as e:
        logger(f"❌ ERREUR : {e}")
    finally:
        st.session_state.log_queue.put("__DONE__")

# ----------------------------------------------------------
# Lancement des tâches
# ----------------------------------------------------------
def _start_task(task_name: str):
    if st.session_state.busy:
        return

    st.session_state.logs = []
    st.session_state.log_queue = queue.Queue()
    st.session_state.task = task_name
    st.session_state.busy = True

    t = threading.Thread(
        target=_worker,
        args=(task_name, st.session_state.selected_school),
        daemon=True
    )
    st.session_state.worker = t
    t.start()

# ----------------------------------------------------------
# UI Controls
# ----------------------------------------------------------
col1, col2, col3, col4 = st.columns([1,1,1,1])
with col1:
    st.button(
        "Scraper plateformes web",
        disabled=st.session_state.busy,
        on_click=lambda: _start_task("web")
    )
with col2:
    st.button(
        "Avis Google Business",
        disabled=st.session_state.busy,
        on_click=lambda: _start_task("gmb")
    )
with col3:
    st.button(
        "Mettre à jour le Sommaire",
        disabled=st.session_state.busy,
        on_click=lambda: _start_task("summary")
    )
with col4:
    st.button(
        "🧹 Effacer les logs",
        disabled=st.session_state.busy,
        on_click=lambda: st.session_state.logs.clear()
    )

# Téléchargement logs
if st.session_state.logs:
    export_txt = "\n".join(
        f"[{r['ts']}] {r['msg']}" 
        for r in st.session_state.logs
    )
    st.download_button(
        "⬇️ Télécharger les logs",
        data=export_txt,
        file_name="logs.txt",
        disabled=st.session_state.busy
    )

# ----------------------------------------------------------
# Rendu + streaming
# ----------------------------------------------------------
_drain_queue()
_render_logs()

# Rafraîchissement automatique tant que worker actif
if st.session_state.busy:
    st.experimental_rerun()
