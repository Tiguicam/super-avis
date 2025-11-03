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

# Session state
if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []              # historique affiché
if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"

# Ces deux clés seront recréées à CHAQUE nouveau run (anti-doublon par exécution)
if "run_id" not in st.session_state:
    st.session_state.run_id = None          # id courant d'exécution (None si rien en cours)
if "seen_in_run" not in st.session_state:
    st.session_state.seen_in_run = set()    # (run_id, msg) déjà ajoutés pour CE run
if "header_done_for" not in st.session_state:
    st.session_state.header_done_for = set()  # run_ids pour lesquels l'entête a été ajoutée

# ------------------------------ ECOLES ------------------------------
ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]
st.session_state.selected_school = st.selectbox(
    "Sélectionne une école :",
    ECOLES,
    index=ECOLES.index(st.session_state.selected_school),
    disabled=st.session_state.busy,  # évite les relances pendant un run
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
    """
    Ajoute une ligne SI pas déjà vue pour le run courant.
    Dédupe strictement par (run_id, msg) → aucune répétition même si Streamlit rerun.
    """
    msg = (msg or "").strip()
    if not msg or st.session_state.run_id is None:
        return
    key = (st.session_state.run_id, msg)
    if key in st.session_state.seen_in_run:
        return
    st.session_state.seen_in_run.add(key)
    st.session_state.logs.append({"ts": _now_hms(), "msg": msg})
    render_logs()
    # petit yield pour laisser l'UI peindre pendant un long traitement
    time.sleep(0.01)

render_logs()

# ------------------------------ RUNNER ------------------------------
def _start_run(task: str, school: str):
    """Démarre une exécution synchrone isolée par run_id + anti-doublon local."""
    if st.session_state.busy:
        return
    st.session_state.busy = True
    # nouveau run → nouveau run_id et reset du set de déduplication local
    st.session_state.run_id = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    st.session_state.seen_in_run = set()

    # entête du run (garantie 1x pour ce run)
    if st.session_state.run_id not in st.session_state.header_done_for:
        header = f"— RUN { _now_hms() } • {task.upper()} • {school} —"
        append_log(header)
        st.session_state.header_done_for.add(st.session_state.run_id)

    append_log("⏳ En cours…")

    def logger(m):
        # tout ce que tes scripts loguent passe ici → dédupe (run_id, msg)
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
        # fin du run
        st.session_state.busy = False
        st.session_state.run_id = None  # ferme l’exécution courante

# ------------------------------ BOUTONS ------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.button(
        "Scraper plateformes web",
        disabled=st.session_state.busy,
        on_click=lambda: _start_run("web", st.session_state.selected_school),
    )

with col2:
    st.button(
        "Avis Google Business",
        disabled=st.session_state.busy,
        on_click=lambda: _start_run("gmb", st.session_state.selected_school),
    )

with col3:
    st.button(
        "Mettre à jour le Sommaire",
        disabled=st.session_state.busy,
        on_click=lambda: _start_run("summary", st.session_state.selected_school),
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
