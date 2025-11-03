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
    for ch in ("\u200b", "\u200c", "\ufeff"):
        s = s.replace(ch, "")
    return " ".join(s.strip().split())

# Regex & constantes
URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)
# ponctuation finale élargie (flèches, tirets, guillemets FR, ellipses, etc.)
TRAIL_PUNCT = ")]>;,.!?’’\"—–-→…:»«·"

# LIGNE D'AUTORITÉ (Option A) attendue depuis script_web :
# 📊 CREAD → brut 24 | uniques 17 | sheet +0 | ♻️ MAJ 7
RE_SUMMARY_AUTH = re.compile(
    r"^📊\s*(?P<school>.+?)\s*→\s*brut\s*(?P<brut>\d+)\s*\|\s*uniques\s*(?P<uniques>\d+)\s*\|\s*sheet\s*\+?(?P<sheet>\d+)(?:\s*\|\s*♻️\s*MAJ\s*(?P<maj>\d+))?\s*$",
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

# Stats d'autorité (remplies uniquement si 📊 est émise par script_web)
if "authoritative_summary" not in st.session_state:
    st.session_state.authoritative_summary = None  # dict: {"school","brut","uniques","sheet","+maj"}
if "recap_emitted" not in st.session_state:
    st.session_state.recap_emitted = False

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

# ------------------------------ PARSEUR DU RÉCAP D'AUTORITÉ ------------------------------
def _ingest_authoritative_summary(msg_norm: str):
    """
    Capture la ligne d'autorité émise par script_web :
    📊 SCHOOL → brut N | uniques M | sheet +K | ♻️ MAJ U
    """
    m = RE_SUMMARY_AUTH.search(msg_norm)
    if not m:
        return False

    school = _normalize_msg(m.group("school"))
    brut = int(m.group("brut"))
    uniques = int(m.group("uniques"))
    sheet_added = int(m.group("sheet"))
    maj = int(m.group("maj")) if m.group("maj") is not None else 0

    st.session_state.authoritative_summary = {
        "school": school,
        "brut": brut,
        "uniques": uniques,
        "sheet_added": sheet_added,
        "maj": maj,
    }
    return True

def _maybe_emit_recap_from_authority():
    """
    Si on a reçu la ligne 📊 d'autorité et que le récap n'a pas encore été émis,
    on ajoute une ligne claire "🧾 Récap ..."
    """
    if st.session_state.recap_emitted:
        return
    auth = st.session_state.authoritative_summary
    if not auth:
        return

    school = auth["school"]
    brut = auth["brut"]
    uniques = auth["uniques"]
    sheet_added = auth["sheet_added"]
    # NB: on n'affiche pas MAJ dans le récap final, selon l'option demandée
    append_log(f"🧾 Récap {school} → brut {brut} | uniques {uniques} | ajoutés sheet +{sheet_added}")
    st.session_state.recap_emitted = True

# ------------------------------ LOG APPEND (ATOMIQUE) ------------------------------
def append_log(msg: str):
    """
    Append atomique + dédup via clé stable.
    On évite aussi deux messages strictement identiques d'affilée.
    On ingère la ligne 📊 d'autorité si elle passe.
    """
    raw = str(msg)
    norm = _normalize_msg(raw)
    key = _dedup_key(raw)

    # filet de sécurité: même message que le précédent -> skip
    if st.session_state.last_norm_msg == norm:
        return

    # Ingestion éventuelle du récap d'autorité
    _ingest_authoritative_summary(norm)

    lock = _get_log_lock()
    with lock:
        if _should_skip_by_key(key):
            return
        _remember_key(key)
        st.session_state.logs.append({"ts": _now_hms(), "msg": norm})
        st.session_state.last_norm_msg = norm
        st.session_state.last_key = key

    # essaie d'émettre le récap (si on vient de recevoir la 📊)
    _maybe_emit_recap_from_authority()

    # rafraîchit l'UI
    render_logs()
    time.sleep(0.003)

# ------------------------------ RUNNER ------------------------------
def _start_run(task: str, school: str):
    """
    Lance un run si et seulement si aucun run n'est déjà actif.
    Protégé par un verrou global + garde busy (anti-multi-run).
    """
    # garde immédiate (imperméable aux reruns Streamlit)
    if st.session_state.busy:
        return

    run_lock = _get_run_lock()
    # essai non bloquant: si quelqu'un d'autre tourne, on sort
    if not run_lock.acquire(blocking=False):
        return

    try:
        # anti double-clic très rapproché
        now = time.time()
        if now - st.session_state.last_start_epoch < 0.25:
            return
        st.session_state.last_start_epoch = now

        # marque busy -> bloquera tout nouvel appel jusqu'à libération
        st.session_state.busy = True
        st.session_state.run_id = datetime.now().strftime("%Y%m%d-%H%M%S.%f")
        # reset dédup & panneau vierge par run
        st.session_state.seen_keys = set()
        st.session_state.logs = []
        st.session_state.last_norm_msg = None
        st.session_state.last_key = None
        st.session_state.authoritative_summary = None
        st.session_state.recap_emitted = False

        append_log(f"— RUN {_now_hms()} • {task.upper()} • {school} —")
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

            # si la ligne 📊 n'a pas été reçue, on n'émet rien (Option A = autorité script_web)
            _maybe_emit_recap_from_authority()

            append_log("✅ Terminé")
        except Exception as e:
            append_log(f"❌ ERREUR : {e}")
        finally:
            st.session_state.busy = False
            st.session_state.run_id = None
    finally:
        # libère le verrou de run quoi qu'il arrive
        try:
            run_lock.release()
        except RuntimeError:
            pass

# ------------------------------ BOUTONS (on_click uniquement) ------------------------------
def _on_click_web():
    _start_run("web", st.session_state.selected_school)

def _on_click_gmb():
    _start_run("gmb", st.session_state.selected_school)

def _on_click_summary():
    _start_run("summary", st.session_state.selected_school)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.button("Scraper plateformes web", disabled=st.session_state.busy, on_click=_on_click_web)
with col2:
    st.button("Avis Google Business", disabled=st.session_state.busy, on_click=_on_click_gmb)
with col3:
    st.button("Mettre à jour le Sommaire", disabled=st.session_state.busy, on_click=_on_click_summary)
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
