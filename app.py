import streamlit as st
from datetime import datetime
import script_web
import gmb
import update_summary

# ------------------------------------
# INIT
# ------------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

if "busy" not in st.session_state:
    st.session_state.busy = False

if "logs" not in st.session_state:
    st.session_state.logs = []

if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"


# ------------------------------------
# LISTE ÉCOLES
# ------------------------------------
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

selected = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school),
    disabled=st.session_state.busy,
)
st.session_state.selected_school = selected


# ------------------------------------
# LOG helpers
# ------------------------------------
log_box = st.container()

def add_log(msg: str):
    st.session_state.logs.append({
        "ts": datetime.now().strftime("%H:%M:%S"),
        "msg": str(msg),
    })
    render_logs()

def render_logs():
    if not st.session_state.logs:
        log_box.info("Aucun log.")
        return
    txt = "\n".join(f"- `{x['ts']}` {x['msg']}" for x in st.session_state.logs)
    log_box.markdown(txt)


# ------------------------------------
# WRAPPER
# ------------------------------------
def run_task(func):
    if st.session_state.busy:
        return

    st.session_state.busy = True
    st.session_state.logs = []   # reset une run = clair
    add_log("⏳ En cours…")

    try:
        func(lambda m: add_log(m))
        add_log("✅ Terminé")
    except Exception as e:
        add_log(f"❌ ERREUR : {e}")

    st.session_state.busy = False


# ------------------------------------
# BOUTONS
# ------------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.button(
        "Scraper plateformes web",
        disabled=st.session_state.busy,
        on_click=lambda: run_task(
            lambda logger: script_web.run(
                logger=logger,
                school_filter=st.session_state.selected_school
            )
        )
    )

with col2:
    st.button(
        "Avis Google Business",
        disabled=st.session_state.busy,
        on_click=lambda: run_task(
            lambda logger: gmb.run(
                logger=logger,
                school_filter=st.session_state.selected_school
            )
        )
    )

with col3:
    st.button(
        "Mettre à jour le Sommaire",
        disabled=st.session_state.busy,
        on_click=lambda: run_task(
            lambda logger: update_summary.run(
                logger=logger,
                school_filter=st.session_state.selected_school
            )
        )
    )

with col4:
    st.button(
        "🧹 Effacer logs",
        disabled=st.session_state.busy,
        on_click=lambda: (st.session_state.logs.clear(), render_logs())
    )


# ------------------------------------
# DOWNLOAD
# ------------------------------------
if st.session_state.logs:
    txt = "\n".join(f"[{x['ts']}] {x['msg']}" for x in st.session_state.logs)
    st.download_button(
        "⬇️ Télécharger logs",
        data=txt,
        file_name="logs.txt",
        disabled=st.session_state.busy
    )

render_logs()
