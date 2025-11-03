import streamlit as st
import threading
import queue
from datetime import datetime

import script_web
import gmb
import update_summary

# ------------------------------ INIT ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

if "busy" not in st.session_state:
    st.session_state.busy = False

if "worker" not in st.session_state:
    st.session_state.worker = None

if "log_queue" not in st.session_state:
    st.session_state.log_queue = None

if "logs" not in st.session_state:
    st.session_state.logs = []

if "log_msgs" not in st.session_state:
    st.session_state.log_msgs = set()   # ✅ anti-doublon

if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"


# ------------------------------ ECOLES ------------------------------
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school)
)


# ------------------------------ LOG UI ------------------------------
logs_box = st.container()


def render_logs():
    """Affiche les logs"""
    if not st.session_state.logs:
        logs_box.info("Aucun log pour le moment.")
        return

    txt = "\n".join(
        f"- `{row['ts']}` {row['msg']}" for row in st.session_state.logs
    )
    logs_box.markdown(txt)


def append_log(msg: str):
    """Ajoute un log si nouveau (anti-doublon)"""
    msg = str(msg)

    # Anti-doublon strict
    if msg in st.session_state.log_msgs:
        return

    st.session_state.log_msgs.add(msg)

    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": msg
    })
    render_logs()


def drain_queue(q: queue.Queue | None):
    """Récupère les messages venant du worker"""
    if not q:
        return False
    done = False
    try:
        while True:
            msg = q.get_nowait()
            if msg == "__DONE__":
                done = True
                break
            append_log(msg)
    except queue.Empty:
        pass
    return done


# ------------------------------ WORKER ------------------------------
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


# ------------------------------ START TASK ------------------------------
def start_task(task_name: str):
    if st.session_state.busy:
        return

    # reset logs
    st.session_state.logs = []
    st.session_state.log_msgs = set()

    st.session_state.busy = True

    q = queue.Queue()
    st.session_state.log_queue = q

    t = threading.Thread(target=_worker,
                         args=(task_name, st.session_state.selected_school, q),
                         daemon=True)
    st.session_state.worker = t
    t.start()


# ------------------------------ ACTION BUTTONS ------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.button("Scraper plateformes web",
              disabled=st.session_state.busy,
              on_click=lambda: start_task("web"))

with col2:
    st.button("Avis Google Business",
              disabled=st.session_state.busy,
              on_click=lambda: start_task("gmb"))

with col3:
    st.button("Mettre à jour le Sommaire",
              disabled=st.session_state.busy,
              on_click=lambda: start_task("summary"))

with col4:
    st.button("🧹 Effacer les logs",
              disabled=st.session_state.busy,
              on_click=lambda: st.session_state.logs.clear())


# Download logs
if st.session_state.logs:
    export_txt = "\n".join(
        f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs
    )
    st.download_button("⬇️ Télécharger les logs",
                       data=export_txt,
                       file_name="logs.txt",
                       disabled=st.session_state.busy)


# ------------------------------ QUEUE + DISPLAY ------------------------------
finished = drain_queue(st.session_state.log_queue)

if finished:
    st.session_state.busy = False
    st.session_state.worker = None
    st.session_state.log_queue = None

render_logs()
