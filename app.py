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
st.session_state.selected_school = st.selectbox("Sélectionne une école :", ECOLES, index=ECOLES.index(st.session_state.selected_school))

# ----------------------------------------------------------
# Affichage & helpers logs
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

# Draine la queue -> state.logs (à appeler à chaque rerun)
def _drain_queue():
    q: queue.Queue = st.session_state.log_queue
    if not q:
        return
    try:
        while True:
            msg = q.get_nowait()
            _append_log(msg)
    except queue.Empty:
        pass

# Logger passé aux scripts (écrit dans la queue, non bloquant)
def _make_logger():
    q: queue.Queue = st.session_state.log_queue
    def logger(msg):
        # on met des strings propres seulement
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
        # On signale la fin au thread UI via un message spécial
        st.session_state.log_queue.put("__DONE__")

# ----------------------------------------------------------
# Lancement / fin & UI
# ----------------------------------------------------------
def _start_task(task_name: str):
    if st.session_state.busy:
        return
    # reset
    st.session_state.logs = []
    st.session_state.log_queue = queue.Queue()
    st.session_state.task = task_name
    st.session_state.busy = True
    # démarre le worker
    t = threading.Thread(target=_worker, args=(task_name, st.session_state.selected_school), daemon=True)
    st.session_state.worker = t
    t.start()

def _stop_task():
    # NOTE: sans coopérative d'arrêt dans les scripts, on ne peut pas tuer proprement.
    # Ici on se contente d'indiquer la fin visuelle; option "stop" réelle requiert que
    # script_web/gmb checkent un flag. On ne l’active pas pour l’instant.
    _append_log("⏹ Arrêt demandé (arrêt immédiat non supporté).")
    # affichage seulement
    _render_logs()

# Boutons d’action
col1, col2, col3, col4 = st.columns([1,1,1,1])
with col1:
    st.button("Scraper plateformes web", disabled=st.session_state.busy, on_click=lambda: _start_task("web"))
with col2:
    st.button("Avis Google Business", disabled=st.session_state.busy, on_click=lambda: _start_task("gmb"))
with col3:
    st.button("Mettre à jour le Sommaire", disabled=st.session_state.busy, on_click=lambda: _start_task("summary"))
with col4:
    st.button("🧹 Effacer les logs", disabled=st.session_state.busy, on_click=lambda: st.session_state.logs.clear())

# Téléchargement des logs
if st.session_state.logs:
    export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
    st.download_button("⬇️ Télécharger les logs", data=export_txt, file_name="logs.txt", disabled=st.session_state.busy)

# ----------------------------------------------------------
# Boucle "live": on vide la queue et on raffraîchit tant que busy
# ----------------------------------------------------------
_drain_queue()

# Si le worker a envoyé le marqueur de fin, on libère l'UI
if st.session_state.log_queue:
    try:
        # Attention: on ne bloque pas. On vérifie juste le sommet.
        # S'il y a "__DONE__", on libère l'UI.
        peek = st.session_state.log_queue.get_nowait()
        if peek == "__DONE__":
            st.session_state.busy = False
        else:
            # ce n'était pas le marqueur -> on remet le message et on continue
            st.session_state.log_queue.put(peek)
    except queue.Empty:
        pass

# Rendu
_render_logs()

# Auto-refresh doux pendant l’exécution pour “streamer” les lignes
if st.session_state.busy:
    # refraîchit la page toutes les 500ms tant que le thread tourne
    st.experimental_singleton.clear()  # no-op de sécurité
    st.experimental_rerun()  # force un rerun → draine à nouveau la queue et réaffiche
