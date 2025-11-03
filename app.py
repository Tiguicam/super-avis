import streamlit as st
import time
from datetime import datetime

import script_web
import gmb
import update_summary

# ------------------------------ INIT ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

def _now_hms():
    return datetime.now().strftime("%H:%M:%S")

def _normalize_msg(s: str) -> str:
    # dédup agressive: trim, collapse espaces, retire zero-width & CR
    s = (s or "").replace("\r", "").strip()
    parts = s.split()
    return " ".join(parts)

# State
if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []
if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"

# run-local states
if "run_id" not in st.session_state:
    st.session_state.run_id = None
if "seen_in_run" not in st.session_state:
    st.session_state.seen_in_run = set()  # set[(run_id, norm_msg)]
if "header_done_for" not in st.session_state:
    st.session_state.header_done_for = set()  # set[run_id]
if "last_start_epoch" not in st.session_state:
    st.session_state.last_start_epoch = 0.0   # anti double-clic / rerun

# ------------------------------ ECOLES ------------------------------
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school),
    disabled=st.session_state.busy,
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
    """Ajoute une ligne si et seulement si (run_id, msg_normalisé) n'a pas déjà été vu."""
    if st.session_state.run_id is None:
        return
    norm = _normalize_msg(msg)
    if not norm:
        return
    key = (st.session_state.run_id, norm)
    if key in st.session_state.seen_in_run:
        return
    st.session_state.seen_in_run.add(key)
    st.session_state.logs.append({"ts": _now_hms(), "msg": norm})
    render_logs()
    # mini yield pour laisser le temps d'afficher
    time.sleep(0.005)

render_logs()

# ------------------------------ RUNNER ------------------------------
def _start_run(task: str, school: str):
    # anti double-clic/rerun très rapproché (<300ms)
    now = time.time()
    if now - st.session_state.last_start_epoch < 0.3:
        return
    st.session_state.last_start_epoch = now

    if st.session_state.busy:
        return

    st.session_state.busy = True
    st.session_state.run_id = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    st.session_state.seen_in_run = set()  # reset dédup pour CE run

    # entête 1x
    if st.session_state.run_id not in st.session_state.header_done_for:
        append_log(f"— RUN {_now_hms()} • {task.upper()} • {school} —")
        st.session_state.header_done_for.add(st.session_state.run_id)

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
        st.session_state.run_id = None

# ------------------------------ BOUTONS (sans on_click) ------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("Scraper plateformes web", disabled=st.session_state.busy):
        _start_run("web", st.session_state.selected_school)

with col2:
    if st.button("Avis Google Business", disabled=st.session_state.busy):
        _start_run("gmb", st.session_state.selected_school)

with col3:
    if st.button("Mettre à jour le Sommaire", disabled=st.session_state.busy):
        _start_run("summary", st.session_state.selected_school)

with col4:
    if st.button("🧹 Effacer les logs", disabled=st.session_state.busy):
        st.session_state.logs.clear()
        render_logs()

# ------------------------------ EXPORT ------------------------------
if st.session_state.logs:
    export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
    st.download_button(
        "⬇️ Télécharger les logs",
        data=export_txt,
        file_name="logs.txt",
        disabled=st.session_state.busy,
    )
