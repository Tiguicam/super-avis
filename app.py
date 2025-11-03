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
    "log_queue": None,   # queue.Queue quand un job démarre
    "logs": [],
    "task": None,        # "web" | "gmb" | "summary"
    "selected_school": "TOUTES",
    "prev_school": "TOUTES",
    "_last_refresh": 0.0,
    # Progress
    "progress_total": 0,
    "progress_done": 0,
    # Prefs
    "clear_on_school_change": True,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

ECOLES = ["TOUTES", "BRASSART", "CREAD", "EFAP", "EFJ", "ESEC", "ICART", "Ecole bleue"]

top_col1, top_col2 = st.columns([3,1])
with top_col1:
    st.session_state.selected_school = st.selectbox(
        "Sélectionne une école :", ECOLES,
        index=ECOLES.index(st.session_state.selected_school),
    )
with top_col2:
    st.session_state.clear_on_school_change = st.checkbox(
        "Effacer les logs\nquand je change d’école",
        value=st.session_state.clear_on_school_change
    )

# Effacer les logs si on change d’école (pour éviter l’effet “batch” au rerun)
if st.session_state.selected_school != st.session_state.prev_school:
    if st.session_state.clear_on_school_change and not st.session_state.busy:
        st.session_state.logs = []
    st.session_state.prev_school = st.session_state.selected_school

# ------------------------------ Zones dynamiques ------------------------------
progress_ph = st.empty()
log_area = st.empty()

# ------------------------------ Logs helpers ------------------------------
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

def _update_progress():
    """Dessine/MAJ la barre de progression pour 'web'."""
    if st.session_state.task != "web" or st.session_state.progress_total <= 0:
        progress_ph.empty()
        return
    done = st.session_state.progress_done
    total = st.session_state.progress_total
    pct = int((done / total) * 100) if total else 0
    progress_ph.progress(pct, text=f"{pct}% — {done}/{total} URLs traitées")

def _drain_queue(q: "queue.Queue[str] | None") -> bool:
    """
    Vide la queue vers les logs.
    Incrémente la progression si une ligne commence par http(s)://.
    Retourne True si le worker a signalé la fin (__DONE__).
    """
    if not q:
        return False
    done_flag = False
    try:
        while True:
            msg = q.get_nowait()
            if msg == "__DONE__":
                done_flag = True
                break

            # Progression par URL (web uniquement) si la ligne est une URL
            if st.session_state.task == "web":
                s = msg.strip().lower()
                if s.startswith("http://") or s.startswith("https://"):
                    st.session_state.progress_done += 1
                    _update_progress()

            _append_log(msg)
    except queue.Empty:
        pass
    return done_flag

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
def _compute_total_urls_for_web(school: str) -> int:
    """
    Lit le YAML via le module de scraping pour compter le nombre d'URLs
    qui seront traitées pour l'école sélectionnée.
    """
    try:
        cfg = script_web._load_yaml()  # helper existant
        ECOLES = cfg["ecoles"]
        keys = script_web._select_ecoles(ECOLES, school_filter=school, ecoles_choisies=None)
        total = 0
        for k in keys:
            block = ECOLES.get(k) or {}
            urls = block.get("urls", []) or []
            total += len(urls)
        return total
    except Exception:
        return 0

def _start_task(task_name: str):
    if st.session_state.busy:
        return

    # reset logs & progress
    st.session_state.logs = []
    st.session_state.task = task_name
    st.session_state.busy = True
    st.session_state.progress_done = 0
    st.session_state.progress_total = 0

    # Si web → on calcule le total d’URLs pour afficher un %
    if task_name == "web":
        st.session_state.progress_total = _compute_total_urls_for_web(st.session_state.selected_school)
        _update_progress()
    else:
        progress_ph.empty()

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
    st.download_button("⬇️ Télécharger les logs",
                       data=export_txt,
                       file_name="logs.txt",
                       disabled=st.session_state.busy)

# ------------------------------ Streaming & rendu ------------------------------
finished = _drain_queue(st.session_state.log_queue)

if finished:
    # Si web : forcer la barre à 100%
    if st.session_state.task == "web" and st.session_state.progress_total > 0:
        st.session_state.progress_done = st.session_state.progress_total
        _update_progress()

    st.session_state.busy = False
    st.session_state.worker = None
    st.session_state.log_queue = None

# Affichage
_update_progress()
_render_logs()

# Refresh doux tant que ça tourne (~ toutes les 250 ms)
if st.session_state.busy:
    now = time.time()
    if now - st.session_state._last_refresh > 0.25:
        st.session_state._last_refresh = now
        st.rerun()
