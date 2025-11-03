# -*- coding: utf-8 -*-
"""
Extraction des avis Google Business Profile depuis gmb.yaml
OAuth (popup) la 1ère fois -> token.json réutilisé ensuite
Écriture à la suite dans Google Sheets (même format que ton autre script)

Dépendances :
  pip install google-auth google-auth-oauthlib gspread pyyaml python-dateutil
Fichiers requis dans le dossier :
  - gmb.yaml
  - client_secret.json   (OAuth Desktop)
  - service_account.json (pour Sheets en local si pas de st.secrets)
"""

import os, re, yaml
from datetime import datetime
from dateutil import tz

import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request, AuthorizedSession

# -------- CONFIG --------
GMB_YAML_FILE        = "gmb.yaml"
CLIENT_SECRET_FILE   = "client_secret.json"
TOKEN_FILE           = "token.json"
SERVICE_ACCOUNT_JSON = "service_account.json"  # compat local

SCOPE_GMB = ["https://www.googleapis.com/auth/business.manage"]
BASE_URL_V4  = "https://mybusiness.googleapis.com/v4"
BASE_URL_V1  = "https://mybusinessbusinessinformation.googleapis.com/v1"

EXPECTED_HEADERS = [
    "uid", "prenom", "note", "date", "annee",
    "formation", "texte", "url", "etablissement", "ville",
    "reponse_1", "reponse_2", "reponse_3", "site"
]

# ----------------------------------------------------------------
# Auth Sheets (Streamlit + fallback local)
# ----------------------------------------------------------------
def _get_gspread_client():
    """
    - En mode Streamlit : utilise st.secrets["gcp_service_account"]
    - Sinon : lit un fichier service account local (via $GSPREAD_SA_JSON ou SERVICE_ACCOUNT_JSON)
    """
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    except Exception:
        pass
    cred_path = os.getenv("GSPREAD_SA_JSON", SERVICE_ACCOUNT_JSON)
    return gspread.service_account(filename=cred_path)

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def clean(t: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", (t or "")).strip()

def sha1(s: str) -> str:
    import hashlib as _hash
    return _hash.sha1(s.encode("utf-8")).hexdigest()

def compute_uid(*parts) -> str:
    norm = "|".join(clean(str(p)).lower() for p in parts)
    return sha1(norm)

def normalize_ecole(name: str) -> str:
    if not name:
        return ""
    return clean(name).lower()

def normalize_ville(v: str) -> str:
    v = clean(v or "")
    return v[:1].upper() + v[1:] if v else ""

STAR_TO_INT = {
    "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5",
}
def normalize_star(note_raw) -> str:
    if note_raw is None:
        return ""
    s = str(note_raw).strip().upper()
    if s.isdigit():
        return s
    return STAR_TO_INT.get(s, "")

def ensure_headers(ws):
    try:
        header = ws.row_values(1)
    except Exception:
        header = []
    if header != EXPECTED_HEADERS:
        ws.update("A1", [EXPECTED_HEADERS])

# ---- YAML -------------------------------------------------------
def load_gmb_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return (raw.get("gmb") or [])

# ----------------------------------------------------------------
# AUTH (GMB OAuth)
# ----------------------------------------------------------------
def get_user_credentials() -> Credentials:
    """
    Priorité:
    1) Streamlit: st.secrets["gmb_token"] (token.json injecté)
    2) Local: token.json (si présent)
    3) Local: flow OAuth avec client_secret.json (ouvre un navigateur)
    """
    # 1) Streamlit secrets
    try:
        import streamlit as st  # import local pour éviter la dépendance hors cloud
        if "gmb_token" in st.secrets:
            info = dict(st.secrets["gmb_token"])
            # scopes peut être str ou list : normalisons
            scopes_val = info.get("scopes")
            if isinstance(scopes_val, str):
                info["scopes"] = [s.strip() for s in scopes_val.split(",") if s.strip()]
            elif isinstance(scopes_val, list):
                pass
            else:
                info["scopes"] = ["https://www.googleapis.com/auth/business.manage"]

            creds = Credentials.from_authorized_user_info(info, SCOPE_GMB)
            if not creds.valid and creds.refresh_token:
                creds.refresh(Request())
            return creds
    except Exception:
        # On ignore et on tente les options locales
        pass

    # 2) Local: token.json présent -> on le lit
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPE_GMB)
            if not creds.valid and creds.refresh_token:
                creds.refresh(Request())
            return creds
        except Exception:
            pass

    # 3) Local: flow OAuth (nécessite client_secret.json et un navigateur)
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            "client_secret.json introuvable et aucun gmb_token dans st.secrets. "
            "Fais l’auth en local une fois pour générer token.json, "
            "puis copie son contenu dans st.secrets[gmb_token]."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPE_GMB)
    creds = flow.run_local_server(port=0, prompt='consent')
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def build_session(creds: Credentials) -> AuthorizedSession:
    s = AuthorizedSession(creds)
    # FR = empêche Google de renvoyer les avis traduits
    s.headers.update({"Accept-Language": "fr"})
    return s

# ----------------------------------------------------------------
# Sheets
# ----------------------------------------------------------------
def get_sheet(sheet_id: str, tab_name: str = "TEST"):
    gc = _get_gspread_client()
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows="100", cols="20")
    ensure_headers(ws)
    return ws

# ----------------------------------------------------------------
# GMB API
# ----------------------------------------------------------------
def parse_resource_name(resource: str):
    m = re.match(r"^accounts/([\d]+)/locations/([\d]+)$", resource.strip())
    if not m:
        raise ValueError(f"Resource name invalide: {resource}")
    return m.group(1), m.group(2)

def list_reviews_for_location(session, account_id: str, location_id: str, page_size: int = 100):
    name = f"accounts/{account_id}/locations/{location_id}"
    page_token = None
    while True:
        params = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        resp = session.get(f"{BASE_URL_V4}/{name}/reviews", params=params)
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("reviews", []):
            yield r
        page_token = data.get("nextPageToken")
        if not page_token:
            break

# ---- Auto-ville
def get_city_v1(session: AuthorizedSession, location_id: str) -> str:
    try:
        r = session.get(
            f"{BASE_URL_V1}/locations/{location_id}",
            params={"readMask": "storefrontAddress,address"}
        )
        if r.status_code != 200:
            return ""
        data = r.json() or {}
        sfa = data.get("storefrontAddress", {}) or {}
        city = sfa.get("locality") or sfa.get("localityName") or sfa.get("sublocality")
        if city:
            return clean(city)
        addr = data.get("address", {}) or {}
        city = addr.get("locality") or addr.get("localityName") or addr.get("sublocality")
        return clean(city)
    except:
        return ""

def get_city_v4(session: AuthorizedSession, account_id: str, location_id: str) -> str:
    try:
        params = {"readMask": "address,locationName"}
        r = session.get(f"{BASE_URL_V4}/accounts/{account_id}/locations/{location_id}", params=params)
        if r.status_code != 200:
            return ""
        data = r.json() or {}
        addr = data.get("address", {}) or {}
        city = addr.get("locality") or addr.get("localityName") or addr.get("sublocality")
        if city:
            return clean(city)
        locname = clean(data.get("locationName", ""))
        m = re.search(r"-\s*([A-Za-zÀ-ÖØ-öø-ÿ'’\-\s]+)$", locname)
        if m:
            return clean(m.group(1))
        return ""
    except:
        return ""

def autodetect_city(session, account_id: str, location_id: str) -> str:
    city = get_city_v1(session, location_id)
    if city:
        return city
    city = get_city_v4(session, account_id, location_id)
    return city

# ---- Mapping Review → Row
def map_gmb_review_to_row(review: dict, ecole_name: str, account_id: str, location_id: str, ville_val: str = ""):
    reviewer = review.get("reviewer", {}) or {}
    reply    = review.get("reviewReply", {}) or {}

    prenom = clean(reviewer.get("displayName", ""))
    note   = normalize_star(review.get("starRating", ""))
    texte  = clean(review.get("comment", ""))

    date_iso = review.get("createTime", "")
    date_str = date_iso
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        annee = str(dt.year)
    except:
        annee = ""

    review_name = review.get("name", "")
    url = review_name if review_name else f"accounts/{account_id}/locations/{location_id}"

    uid = compute_uid(prenom, texte, date_str, location_id)

    row_dict = {
        "uid": uid,
        "prenom": prenom,
        "note": note,
        "date": date_str,
        "annee": annee,
        "formation": "",
        "texte": texte,
        "url": url,
        "etablissement": normalize_ecole(ecole_name),
        "ville": normalize_ville(ville_val),
        "reponse_1": clean(reply.get("comment", "")),
        "reponse_2": "",
        "reponse_3": "",
        "site": "gmb",
    }
    return [row_dict.get(k, "") for k in EXPECTED_HEADERS], row_dict["uid"]

# ----------------------------------------------------------------
def append_rows_no_duplicates(ws, rows_with_uid):
    existing = set()
    try:
        for r in ws.get_all_records():
            u = str(r.get("uid", "")).strip()
            if u:
                existing.add(u)
    except:
        pass

    to_add = []
    for row, uid in rows_with_uid:
        if uid not in existing:
            to_add.append(row)
            existing.add(uid)

    if to_add:
        ws.append_rows(to_add, value_input_option="RAW")
    return len(to_add)

# ----------------------------------------------------------------
def _iter_locations_from_entry(entry: dict):
    out = []
    for res in entry.get("location_ids", []) or []:
        if isinstance(res, dict):
            out.append((str(res.get("id", "")), entry.get("ville", "") or str(res.get("ville", ""))))
        else:
            out.append((str(res), entry.get("ville", "")))
    return out

def _get_existing_uids(ws):
    existing = set()
    try:
        # rapide: lire UNIQUEMENT la colonne A si ton header est bien en A1 = uid
        uids_col = ws.col_values(1)
        for u in uids_col[1:]:
            u = (u or "").strip()
            if u:
                existing.add(u)
    except:
        pass
    return existing

def _row_to_values(row_dict):
    return [row_dict.get(k, "") for k in EXPECTED_HEADERS]

# ----------------------------------------------------------------
def main(school_filter=None, logger=print, config=None):
    # si l'app Streamlit fournit la config, on l'utilise
    if config is not None:
        gmb_entries = config.get("gmb", [])
    else:
        # fallback lecture fichier en local
        gmb_entries = load_gmb_yaml(GMB_YAML_FILE)
    if not gmb_entries:
        logger("❌ Aucun bloc 'gmb' trouvé")
        return

    creds = get_user_credentials()
    session = build_session(creds)

    filt = (school_filter or "").strip().lower()
    use_filter = bool(filt and filt != "toutes")

    for entry in gmb_entries:
        name = (entry.get("name", "") or "").strip()
        if use_filter and normalize_ecole(name) != normalize_ecole(filt):
            continue

        sheet_id = entry.get("sheet_id", "")
        locs = _iter_locations_from_entry(entry)

        if not name or not sheet_id or not locs:
            logger(f"⚠️ Entrée ignorée: {entry}")
            continue

        logger(f"\n📚 {name}")
        ws = get_sheet(sheet_id, tab_name="TEST")

        ensure_headers(ws)
        existing = _get_existing_uids(ws)

        total_found, total_new = 0, 0
        pending_rows = []  # tous les nouveaux à insérer à la fin

        for resource, ville in locs:
            try:
                account_id, location_id = parse_resource_name(resource)
            except:
                logger(f"❌ location invalide: {resource}")
                continue

            ville_used = ville or autodetect_city(session, account_id, location_id)

            # lister les avis pour CETTE location
            count_found = 0
            new_here = 0
            for rev in list_reviews_for_location(session, account_id, location_id):
                row_list, uid = map_gmb_review_to_row(
                    rev, name, account_id, location_id, ville_val=ville_used
                )
                count_found += 1
                if uid not in existing:
                    pending_rows.append(row_list)
                    existing.add(uid)
                    new_here += 1

            total_found += count_found
            total_new += new_here

            if not ville_used:
                logger(f"  ⚠️ Ville introuvable pour {resource}. Active Business Information API ou renseigne `ville:` dans gmb.yaml.")

            # **une seule ligne** pour cette location
            logger(f"🏷️ {resource} ({ville_used or '—'}) → {count_found} avis  |  +{new_here} nouveaux")

        # push des nouveaux (toutes locations de l'école)
        if pending_rows:
            ws.append_rows(pending_rows, value_input_option="RAW")

        # résumé par école
        logger(f"📊 {name} → total {total_found} avis  |  +{total_new} nouveaux, ♻️ 0 MAJ")
        logger(f"📊 {name} → uniques {total_found}")

    logger("\n✅ FIN\n")


# ----------------------------------------------------------------
def run(logger=print, school_filter=None, config=None):
    import builtins
    _old_print = builtins.print
    try:
        builtins.print = logger
        main(school_filter=school_filter, logger=logger, config=config)
    finally:
        builtins.print = _old_print

