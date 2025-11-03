import streamlit as st
import re
import time
from datetime import datetime
from threading import Lock

import script_web
import gmb
import update_summary

# ------------------------------ INIT ------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

def _now_hms():
    return datetime.now().strftime("%H:%M:%S")

def _normalize_msg(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r", "")
    # supprime caractères invisibles courants
    for ch in ("\u200b", "\u200c", "\ufeff"):
        s = s.replace(ch, "")
    # normalise espaces
    return " ".join(s.strip().split())

# Regex & constantes
URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)
# ponctuation finale élargie (flèches, tirets, guillemets FR, points de suspension, etc.)
TRAIL_PUNCT = ")]>;,.!?’’\"—–-→…:»«·"

# Ressources partagées (verrou global pour append_log)
@st.cache_resource
def _get_log_lock():
    return Lock()

# ------------------------------ STATE GLOBAL ------------------------------
if "busy" not in st.session_state:
    st.session_state.busy = False
if "logs" not in st.session_state:
    st.session_state.logs = []
if "selected_school" not in st.session_state:
    st.session_state.selected_school = "TOUTES"

# State par RUN
if "run_id" not in st.session_state:
    st.session_state.run_id = None
if "seen_keys" not in st.session_state:
    st.session_state.seen_keys = set()  # clés de déduplication vues durant ce run
if "last_start_epoch" not in st.session_state:
    st.session_state.last_start_epoch = 0.0

# mémorise le dernier message normalisé et la dernière clé (filet de sécu)
if "last_norm_msg" not in st.session_state:
    st.session_state.last_norm_msg = None
if "last_key" not in st.session_state:
    st.session_state.last_key = None

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

render_logs()

# ------------------------------ DEDUP HELPERS ------------------------------
def _dedup_key(raw_msg: str) -> str:
    """
    Clé de déduplication stable :
    - priorité à l'URL si elle existe (sans ponctuation finale élargie)
    - sinon messages 'système' mappés sur une clé fixe
    - sinon message normalisé (sans '— RUN HH:MM:SS • ... —')
    """
    s = str(raw_msg)

    # messages système courants -> clé fixe
    txt = _normalize_msg(s)
    if txt == "⏳ En cours…":
        return "sys::pending"
    if txt == "✅ Terminé":
        return "sys::done"
    if txt.startswith("— RUN"):
        return "sys::run_start"
    if txt.startswith("🎯 Filtre école"):
        # inclure l'école pour autoriser un changement d'école
        m = re.search(r"Filtre école:\s*([^\|]+)", txt)
        school = _normalize_msg(m.group(1)) if m else ""
        return f"sys::filter::{school.lower()}"
    if txt.startswith("📚 Collecte pour"):
        m = re.search(r"Collecte pour\s+(.+?)…?$", txt)
        school = _normalize_msg(m.group(1)) if m else ""
        return f"sys::collect::{school.lower()}"

    # URL prioritaire
    m = URL_RE.search(s)
    if m:
        url = m.group(1).rstrip(TRAIL_PUNCT)
        return f"url::{url.lower()}"

    # enlève un éventuel préfixe de type '— RUN HH:MM:SS • ... —'
    s2 = re.sub(
        r"^—\s*RUN\s*\d{2}:\d{2}:\d{2}\s*•\s*[^—]+—\s*",
        "",
        s,
        flags=re.IGNORECASE
    )
    s2 = _normalize_msg(s2).lower()
    return f"msg::{s2}"

def _should_skip_by_key(key: str) -> bool:
    if not key:
        return True
    if st.session_state.run_id is None:
        # pas de run actif -> on n'affiche rien
        return True
    return key in st.session_state.seen_keys

def _remember_key(key: str):
    st.session_state.seen_keys.add(key)

# ------------------------------ LOG APPEND (ATOMIQUE) ------------------------------
def append_log(msg: str):
    """
    Append atomique + dédup via clé stable.
    On évite aussi deux messages strictement identiques d'affilée.
    """
    raw = str(msg)
    norm = _normalize_msg(raw)
    key = _dedup_key(raw)

    # filet de sécurité: même message que le précédent -> skip
    if st.session_state.last_norm_msg == norm:
        return

    lock = _get_log_lock()
    with lock:
        if _should_skip_by_key(key):
            return
        _remember_key(key)
        st.session_state.logs.append({"ts": _now_hms(), "msg": norm})
        st.session_state.last_norm_msg = norm
        st.session_state.last_key = key

    # rafraîchit l'UI
    render_logs()
    time.sleep(0.003)

# ------------------------------ RUNNER ------------------------------
def _start_run(task: str, school: str):
    # anti double-clic / rerun rapproché
    now = time.time()
    if now - st.session_state.last_start_epoch < 0.25:
        return
    st.session_state.last_start_epoch = now
    if st.session_state.busy:
        return

    st.session_state.busy = True
    st.session_state.run_id = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    # reset dédup & panneau vierge par run
    st.session_state.seen_keys = set()
    st.session_state.logs = []
    st.session_state.last_norm_msg = None
    st.session_state.last_key = None

    append_log(f"— RUN {_now_hms()} • {task.upper()} • {school} —")
    append_log("⏳ En cours…")

    def logger(m):
        # tous les scripts passent ici
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

# ------------------------------ BOUTONS ------------------------------
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
