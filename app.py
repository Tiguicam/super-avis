import streamlit as st
import threading
import queue
from datetime import datetime

import script_web
import gmb
import update_summary


# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")


# =========================
# INIT SESSION STATE
# =========================
defaults = {
    "busy": False,
    "worker": None,
    "log_queue": None,
    "logs": [],
    "task": None,
    "selected_school": "TOUTES",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================
# ÉCOLES
# =========================
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]

with st.form("school_form", clear_on_submit=False):
    school_choice = st.selectbox(
        "Sélectionne une école :",
        ECOLES,
        index=ECOLES.index(st.session_state.selected_school),
        disabled=st.session_state.busy,
    )
    apply_btn = st.form_submit_button("✅ Appliquer")

if apply_btn:
    st.session_state.selected_school = school_choice


# =========================
# LOGS
# =========================
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
    txt = "\n".join(f"- `{x['ts']}` {x['msg']}" for x in st.session_state.logs)
    log_area.markdown(txt)


def _drain_queue(q: queue.Queue | None):
    if not q:
        return False
    finished = False
    try:
        while True:
            m = q.get_nowait()
            if m == "__DONE__":
                finished = True
                break
            _append_log(m)
    except queue.Empty:
        pass
    return finished


# =========================
# BACKGROUND WORKER
# =========================
def _worker(task: str, school: str, q: queue.Queue):
    def logger(m):
        q.put(str(m))

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
        q.put("__DONE__")


# =========================
# START TASK
# =========================
def _start_task(task_name: str):
    if st.session_state.busy:
        return

    # keep logs — NO CLEAR HERE
    st.session_state.task = task_name
    st.session_state.busy = True

    q = queue.Queue()
    st.session_state.log_queue = q

    t = threading.Thread(target=_worker,
                         args=(task_name, st.session_state.selected_school, q),
                         daemon=True)
    st.session_state.worker = t
    t.start()


# =========================
# UI BUTTONS
# =========================
col1, col2, col3, col4 = st.columns(4)

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


# Download logs
if st.session_state.logs:
    txt = "\n".join(f"[{x['ts']}] {x['msg']}" for x in st.session_state.logs)
    st.download_button(
        "⬇️ Télécharger les logs",
        data=txt,
        file_name="logs.txt",
        disabled=st.session_state.busy
    )


# =========================
# STREAMING
# =========================
# lire ce que le thread a envoyé
finished = _drain_queue(st.session_state.log_queue)

if finished:
    st.session_state.busy = False
    st.session_state.worker = None
    st.session_state.log_queue = None

_render_logs()

# refresh tant que ça tourne
if st.session_state.busy:
    st.autorefresh(interval=800, key="__log_refresh__")
