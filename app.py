import streamlit as st
import re
import time
import uuid
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
    for ch in ("\u200b", "\u200c", "\ufeff"):
        s = s.replace(ch, "")
    return " ".join(s.strip().split())

# Regex & constantes
URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)
TRAIL_PUNCT = ")]>;,.!?’’\"—–-→…:»«·"  # ponctuation finale élargie

# 📊 Formats parsés
# 1) Total brut: "📊 CREAD → total 24 avis | +0 nouveaux, ♻️ 7 MAJ"
RE_TOTAL_BRUT = re.compile(
    r"^📊\s*(?P<school>.+?)\s*→\s*total\s*(?P<brut>\d+)\s*avis\s*\|\s*\+(?P<new>\d+)\s*nouveaux,?\s*♻️\s*(?P<maj>\d+)\s*MAJ\s*$",
    re.IGNORECASE
)

# 2) Uniques: l'une de ces variantes
#    - "📊 CREAD → uniques 17"
#    - "📊 CREAD → total avis uniques 17"
#    - "📊 CREAD → écrit sheet 17"
RE_UNIQUES = re.compile(
    r"^📊\s*(?P<school>.+?)\s*→\s*(?:uniques|total\s*avis\s*uniques|(?:écrit|ecrit)\s*sheet)\s*(?P<uniques>\d+)\s*$",
    re.IGNORECASE
)

# Ressources partagées (verrous)
@st.cache_resource
def _get_log_lock():
    return Lock()

@st.cache_resource
def _get_run_lock():
    # verrou maître: un seul run à la fois au niveau process
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
    st.session_state.seen_keys = set()
if "last_start_epoch" not in st.session_state:
    st.session_state.last_start_epoch = 0.0
if "last_norm_msg" not in st.session_state:
    st.session_state.last_norm_msg = None
if "last_key" not in st.session_state:
    st.session_state.last_key = None

# Un seul run à la fois (token unique)
if "active_run_token" not in st.session_state:
    st.session_state.active_run_token = None

# Stockage des infos parsées pour synthèse finale
if "final_parts" not in st.session_state:
    st.session_state.final_parts = {}  # school -> {"brut":int,"new":int,"maj":int,"uniques":int}
if "final_emitted" not in st.session_state:
    st.session_state.final_emitted = set()  # schools déjà synthétisées

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
    txt = _normalize_msg(s)

    # messages système courants -> clé fixe
    if txt == "⏳ En cours…":
        return "sys::pending"
    if txt == "✅ Terminé":
        return "sys::done"
    if txt.startswith("— RUN"):
        return "sys::run_start"
    if txt.startswith("🎯 Filtre école"):
        m = re.search(r"Filtre école:\s*([^\|]+)", txt)
        school = _normalize_msg(m.group(1)) if m else ""
        return f"sys::filter::{school.lower()}"
    if txt.startswith("📚 Collecte pour"):
        m = re.search(r"Collecte pour\s+(.+?)…?$", txt)
        school = _normalize_msg(m.group(1)) if m else ""
        return f"sys::collect::{school.lower()}"
    if txt.startswith("📊 "):
        return "sys::summary::" + txt.lower()
    
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

# ------------------------------ PARSING & SYNTHÈSE ------------------------------
def _capture_parts(msg_norm: str):
    """
    Capture les morceaux de la ligne finale :
    - brut/new/maj depuis "total ... | +... nouveaux, ♻️ ... MAJ"
    - uniques depuis "uniques N" ou "écrit sheet N"
    Quand on a tout pour une école, on émet la synthèse finale.
    """
    m_total = RE_TOTAL_BRUT.search(msg_norm)
    if m_total:
        school = _normalize_msg(m_total.group("school"))
        d = st.session_state.final_parts.setdefault(school, {})
        d["brut"] = int(m_total.group("brut"))
        d["new"] = int(m_total.group("new"))
        d["maj"] = int(m_total.group("maj"))
        _maybe_emit_final(school)
        return True

    m_uni = RE_UNIQUES.search(msg_norm)
    if m_uni:
        school = _normalize_msg(m_uni.group("school"))
        d = st.session_state.final_parts.setdefault(school, {})
        d["uniques"] = int(m_uni.group("uniques"))
        _maybe_emit_final(school)
        return True

    return False

def _maybe_emit_final(school: str):
    """
    Émet la ligne finale exactement au format demandé quand on a :
    - brut
    - uniques ( = "écrit sheet")
    - new
    - maj
    Une seule émission par école.
    """
    if school in st.session_state.final_emitted:
        return
    d = st.session_state.final_parts.get(school, {})
    needed = all(k in d for k in ("brut", "uniques", "new", "maj"))
    if not needed:
        return
    append_log(f"📊 {school} → brut {d['brut']} | écrit sheet {d['uniques']} | +{d['new']} nouveaux | maj +{d['maj']}")
    st.session_state.final_emitted.add(school)

# ------------------------------ LOG APPEND (ATOMIQUE) ------------------------------
def append_log(msg: str):
    """
    Append atomique + dédup via clé stable.
    On évite aussi deux messages strictement identiques d'affilée.
    On capture les morceaux de la ligne finale si on les voit passer.
    """
    raw = str(msg)
    norm = _normalize_msg(raw)
    key = _dedup_key(raw)

    # filet de sécurité: même message que le précédent -> skip
    if st.session_state.last_norm_msg == norm:
        return

    # Capture des morceaux avant l'ajout dans la liste (pour pouvoir réémettre via append_log)
    _capture_parts(norm)

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
    """
    Lance un run si et seulement si aucun run n'est déjà actif.
    Protégé par un verrou global + garde busy + token de run.
    """
    # Garde immédiate
    if st.session_state.busy or st.session_state.active_run_token is not None:
        return

    run_lock = _get_run_lock()
    if not run_lock.acquire(blocking=False):
        return

    # Alloue un token unique pour ce run
    token = str(uuid.uuid4())
    st.session_state.active_run_token = token

    try:
        now = time.time()
        if now - st.session_state.last_start_epoch < 0.25:
            return
        st.session_state.last_start_epoch = now

        st.session_state.busy = True
        st.session_state.run_id = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
        # reset par run
        st.session_state.seen_keys = set()
        st.session_state.logs = []
        st.session_state.last_norm_msg = None
        st.session_state.last_key = None
        st.session_state.final_parts = {}
        st.session_state.final_emitted = set()

        append_log(f"— RUN {_now_hms()} • {task.upper()} • {school} —")
        append_log("⏳ En cours…")

        def logger(m):
            # Ignore tout log qui arriverait d'un "run zombie"
            if st.session_state.active_run_token != token:
                return
            append_log(str(m))

        try:
            if task == "web":
                script_web.run(logger=logger, school_filter=school)
            elif task == "gmb":
                gmb.run(logger=logger, school_filter=school)
            elif task == "summary":
                update_summary.run(logger=logger, school_filter=school)

            # Si on n'a pas reçu les "uniques", informe clairement
            school_key = school.strip()
            parts = st.session_state.final_parts.get(school_key) or \
                    (st.session_state.final_parts.get(school_key.upper())) or \
                    (st.session_state.final_parts.get(school_key.lower()))
            if not parts or "uniques" not in parts:
                append_log(f"⚠️ Pas de ligne 'uniques' reçue pour {school}. Ajoute dans script_web : "
                           f"📊 {school} → uniques <N>  (ou)  📊 {school} → écrit sheet <N>")

            append_log("✅ Terminé")
        except Exception as e:
            append_log(f"❌ ERREUR : {e}")
        finally:
            st.session_state.busy = False
            st.session_state.run_id = None
            # Libère le token si c'est bien notre run
            if st.session_state.active_run_token == token:
                st.session_state.active_run_token = None
    finally:
        try:
            run_lock.release()
        except RuntimeError:
            pass

# ------------------------------ BOUTONS (on_click uniquement + keys) ------------------------------
def _on_click_web():
    _start_run("web", st.session_state.selected_school)

def _on_click_gmb():
    _start_run("gmb", st.session_state.selected_school)

def _on_click_summary():
    _start_run("summary", st.session_state.selected_school)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.button("Scraper plateformes web", key="btn_web", disabled=st.session_state.busy, on_click=_on_click_web)
with col2:
    st.button("Avis Google Business", key="btn_gmb", disabled=st.session_state.busy, on_click=_on_click_gmb)
with col3:
    st.button("Mettre à jour le Sommaire", key="btn_summary", disabled=st.session_state.busy, on_click=_on_click_summary)
with col4:
    if st.button("🧹 Effacer les logs", key="btn_clear", disabled=st.session_state.busy):
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
