import streamlit as st
import threading
import queue
import time
from datetime import datetime

import script_web
import gmb
import update_summary

# ------------------------------ UI de base ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

# State initial
defaults = {
    "busy": False,
    "worker": None,
    "log_queue": None,   # sera une queue.Queue quand un job démarre
    "logs": [],
    "task": None,        # "web" | "gmb" | "summary"
    "selected_school": "TOUTES",
    "_last_refresh": 0.0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :", ECOLES, index=ECOLES.index(st.session_state.selected_school)
)

# ------------------------------ Logs helpers ------------------------------
log_area = st.empty()

def _append_log(msg: str):
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": str(msg),
    })

def _render_logs():
    if not st.session_state.logs:
        log_area.info("Aucun log pour le moment.")
        return
    txt = "\n".join(f"- `{r['ts']}` {r['msg']}" for r in st.session_state.logs)
    log_area.markdown(txt)

def _drain_queue(q: "queue.Queue[str] | None") -> bool:
    """Vide la queue vers les logs. Retourne True si le worker a signalé la fin (__DONE__)."""
    if not q:
        return False
    done = False
    try:
        while True:
            msg = q.get_nowait()
            if msg == "__DONE__":
                done = True
                break
            _append_log(msg)
    except queue.Empty:
        pass
    return done

# ------------------------------ Worker thread ------------------------------
def _worker(task: str, school: str, q: "queue.Queue[str]"):
    """NE PAS toucher st.session_state ici."""
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

# ------------------------------ Lancement / UI ------------------------------
def _start_task(task_name: str):
    if st.session_state.busy:
        return
    # reset
    st.session_state.logs = []
    st.session_state.task = task_name
    st.session_state.busy = True

    q: "queue.Queue[str]" = queue.Queue()
    st.session_state.log_queue = q

    t = threading.Thread(
        target=_worker,
        args=(task_name, st.session_state.selected_school, q),
        daemon=True
    )
    st.session_state.worker = t
    t.start()

col1, col2, col3, col4 = st.columns([1,1,1,1])
with col1:
    st.button("Scraper plateformes web",
              disabled=st.session_state.busy,
              on_click=lambda: _start_task("web"))
with col2:
    st.button("Avis Google Business",
              disabled=st.session_state.busy,
              on_click=lambda: _start_task("gmb"))
with col3:
    st.button("Mettre à jour le Sommaire",
              disabled=st.session_state.busy,
              on_click=lambda: _start_task("summary"))
with col4:
    st.button("🧹 Effacer les logs",
              disabled=st.session_state.busy,
              on_click=lambda: st.session_state.logs.clear())

# bouton de téléchargement
if st.session_state.logs:
    export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
    st.download_button("⬇️ Télécharger les logs", data=export_txt,
                       file_name="logs.txt",
                       disabled=st.session_state.busy)

# ------------------------------ Streaming & rendu ------------------------------
# 1) récupérer ce que le worker a envoyé depuis la dernière frame
finished = _drain_queue(st.session_state.log_queue)

# 2) si fini, libérer l'UI
if finished:
    st.session_state.busy = False
    st.session_state.worker = None
    st.session_state.log_queue = None

# 3) afficher
_render_logs()

# 4) rafraîchir gentiment tant qu’un job tourne (≈ toutes les 500 ms)
if st.session_state.busy:
    now = time.time()
    if now - st.session_state._last_refresh > 0.5:
        st.session_state._last_refresh = now
        st.rerun()
