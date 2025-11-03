# script_web.py
# Version "headless" pour être lancée depuis le launcher (une seule UI)
# -> pas de fenêtre Tkinter ici
# -> expose run(logger=print, school_filter=None, ecoles_choisies=None)

import os
import re
import time
import yaml
import random
import hashlib
import requests
import gspread

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs, urlencode
from gspread.utils import rowcol_to_a1
from datetime import datetime
from dateutil.relativedelta import relativedelta

# === CONFIG ===
YAML_FILES = ["ecole.yaml", "ecoles.yaml"]  # on tente ecole.yaml puis ecoles.yaml
CREDENTIALS_FILE = "service_account.json"  # gardé pour compat (fallback local)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

EXPECTED_HEADERS = [
    "uid", "prenom", "note", "date", "annee",
    "formation", "texte", "url", "etablissement", "ville",
    "reponse_1", "reponse_2", "reponse_3", "site"
]

# --- AUTH GOOGLE SHEETS (Streamlit + fallback local) ---
def _get_gspread_client():
    """
    - En mode Streamlit : utilise st.secrets["gcp_service_account"]
    - Sinon : lit un fichier service account local (chemin via $GSPREAD_SA_JSON ou 'service_account.json')
    """
    try:
        import streamlit as st  # import local pour éviter la dépendance hors Streamlit
        if "gcp_service_account" in st.secrets:
            return gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    except Exception:
        # On ignore toute erreur et on retombe sur le mode local
        pass

    cred_path = os.getenv("GSPREAD_SA_JSON", CREDENTIALS_FILE)
    return gspread.service_account(filename=cred_path)

# === HELPERS ===
def clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()

def norm(t: str) -> str:
    return clean(t.lower())

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def compute_uid(*args) -> str:
    return sha1("|".join(norm(str(a)) for a in args))

def set_query_param(url, key, value):
    parts = list(urlparse(url))
    q = parse_qs(parts[4], keep_blank_values=True)
    q[key] = [str(value)]
    parts[4] = urlencode(q, doseq=True)
    return urlunparse(parts)

def soft_key_from_values(site: str, prenom: str, texte: str) -> str:
    """
    Clé 'souple' STABLE et indépendante de l'URL.
    Sert à reconnaître un même avis (ex: Custplace campus vs Custplace marque).
    """
    s = (site or "").strip().lower()
    p = (prenom or "").strip().lower()
    t = (texte or "").strip().lower()
    return compute_uid("web-soft", s, p, t)

# === NORMALISATION NOM ÉCOLE ===
def normalize_ecole(name: str) -> str:
    if not name:
        return ""
    n = name.lower().strip("-_ ")
    mapping = {
        "ecole-bleue": "ecole bleue",
        "ecolebleue": "ecole bleue",
        "ecole bleu": "ecole bleue",
        "efap": "efap",
        "icart": "icart",
        "efj": "efj",
        "lefj": "efj",
        "cread": "cread",
        "mopa": "mopa",
        "esec": "ésec",
        "brassart": "brassart",
    }
    return mapping.get(n, n.replace("-", " "))

# === YEAR PARSER ===
def parse_relative_date(text: str):
    now = datetime.now()
    m = re.search(r"il y a (\d+)\s*(mois|an|ans)", (text or "").lower())
    if not m:
        return ""
    value, unit = int(m.group(1)), m.group(2)
    if "mois" in unit:
        dt = now - relativedelta(months=value)
    else:
        dt = now - relativedelta(years=value)
    return str(dt.year)

# === OVERRIDES & DETECTIONS ===
URL_OVERRIDES = {
    # custplace
    "https://fr.custplace.com/ecole-des-nouveaux-metiers-de-la-communication-lille-10": ("efap", "lille"),
    "https://fr.custplace.com/ecole-des-nouveaux-metiers-de-la-communication-paris-10": ("efap", "paris"),
    "https://fr.custplace.com/ecole-des-nouveaux-metiers-de-la-communication-lyon-10": ("efap", "lyon"),
    "https://fr.custplace.com/ecole-des-nouveaux-metiers-de-la-communication-bordeaux-10": ("efap", "bordeaux"),
    "https://fr.custplace.com/computer-graphics-animation-school-arles-10": ("mopa", "arles"),
    "https://fr.custplace.com/icart-lecole-des-metiers-de-la-culture-et-du-commerce-de-lart-paris-10": ("icart", "paris"),
    "https://fr.custplace.com/icart-lecole-des-metiers-de-la-culture-et-du-commerce-de-lart-bordeaux-10": ("icart", "bordeaux"),
    "https://fr.custplace.com/ecole-superieure-detudes-cinematographiques-paris-10": ("ésec", "paris"),
    "https://fr.custplace.com/cread-enseignement-superieur-en-architecture-interieure-et-design-global-lyon-10": ("cread", "lyon"),
    "https://fr.custplace.com/ecole-francaise-de-journalisme-paris-10": ("efj", "paris"),
    "https://fr.custplace.com/ecole-francaise-de-journalisme-bordeaux-10": ("efj", "bordeaux"),
    "https://fr.custplace.com/ecole-brassart-toulouse-toulouse-10": ("brassart", "toulouse"),
    "https://fr.custplace.com/ecole-brassart-caen-caen-10": ("brassart", "caen"),
    "https://fr.custplace.com/ecole-brassart-grenoble-grenoble-10": ("brassart", "grenoble"),
    "https://fr.custplace.com/ecole-brassart-nantes-nantes-10": ("brassart", "nantes"),
    "https://fr.custplace.com/ecole-brassart-tours-tours-10": ("brassart", "tours"),
    # diplomeo
    "https://diplomeo.com/avis-cread_l_ecole_de_reference_en_architecture_interieure_lille-12376": ("cread", "lille"),
    "https://diplomeo.com/avis-brassart_aix_en_provence_l_ecole_des_metiers_de_la_creation-11673": ("brassart", "aix-en-provence"),
}

CITY_KEYWORDS = {
    "paris": "paris",
    "bordeaux": "bordeaux",
    "toulouse": "toulouse",
    "caen": "caen",
    "nantes": "nantes",
    "tours": "tours",
    "annecy": "annecy",
    "montpellier": "montpellier",
    "strasbourg": "strasbourg",
    "lyon": "lyon",
    "aix-en-provence": "aix-en-provence",
    "lille": "lille",
    "rennes": "rennes",
    "arles": "arles",
}

ETAB_KEYWORDS = {
    "cread": "cread",
    "brassart": "brassart",
    "efj": "efj",
    "esec": "ésec",
    "ecole-bleue": "ecole bleue",
    "ecole-bleu": "ecole bleue",
    "icart": "icart",
    "mopa": "mopa",
    "efap": "efap",
}

def detect_city_from_url(url: str) -> str:
    url_low = url.lower()
    for key, city in CITY_KEYWORDS.items():
        if key in url_low:
            return city
    return ""

def detect_etab_from_url(url: str) -> str:
    url_low = url.lower()
    for key, etab in ETAB_KEYWORDS.items():
        if key in url_low:
            return etab
    return ""

# === GOOGLE SHEETS ===
def get_sheet(sheet_id: str, worksheet_name: str = "TEST"):
    gc = _get_gspread_client()
    return gc.open_by_key(sheet_id).worksheet(worksheet_name)

def ensure_headers(sheet):
    try:
        header = sheet.row_values(1)
    except Exception:
        header = []
    if not header:
        sheet.update("A1", [EXPECTED_HEADERS])

# === DIPLOMEO ===
ITEM_SEL_DIP = 'li[data-cy="review-commun-list-item"]'

def parse_etablissement_ville_diplomeo(url: str):
    if url in URL_OVERRIDES:
        etab, ville = URL_OVERRIDES[url]
        return normalize_ecole(etab), ville.lower()
    try:
        path = urlparse(url).path
        m = re.search(r"avis-([^_]+)_([^_]+)", path)
        if m:
            etab = normalize_ecole(m.group(1))
            ville = m.group(2).replace("-", " ").lower()
            return etab, ville
    except Exception:
        pass
    return normalize_ecole(detect_etab_from_url(url)), detect_city_from_url(url)

def extract_reviews_diplomeo(soup, url, etab, ville):
    data = []
    for li in soup.select(ITEM_SEL_DIP):
        prenom  = clean(li.select_one("h3").get_text() if li.select_one("h3") else "")
        note = clean(li.select_one('[data-cy="review-commun-list-item-rating"]').get_text() if li.select_one('[data-cy="review-commun-list-item-rating"]') else "")
        date_rel = clean(li.select_one('[data-cy="review-commun-list-item-createdAt"]').get_text() if li.select_one('[data-cy="review-commun-list-item-createdAt"]') else "")
        txt_long = li.select_one('[data-collapse-target="toCollapse2"]')
        texte = clean(txt_long.get_text()) if txt_long and clean(txt_long.get_text()) else clean(li.get_text(" ", strip=True))
        formation = clean(li.select_one('[data-collapse-target="toCollapse"] .tw-text-heading-xs').get_text() if li.select_one('[data-collapse-target="toCollapse"] .tw-text-heading-xs') else "")

        annees = re.findall(r"\b(\d{4})\b", date_rel + " " + texte)
        annee = ", ".join(sorted(set(annees))) if annees else ""
        if not annee:
            calc = parse_relative_date(date_rel)
            if calc:
                annee = calc

        data.append({
            # UID STABLE (laisse l'URL pour tracer la source exacte)
            "uid": compute_uid("web", url, prenom, texte),
            "prenom": prenom, "note": note, "date": date_rel, "annee": annee,
            "formation": formation, "texte": texte,
            "url": url, "etablissement": normalize_ecole(etab), "ville": ville,
            "reponse_1": "", "reponse_2": "", "reponse_3": "", "site": "diplomeo"
        })
    return data

def scrape_diplomeo(url):
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(url, timeout=20); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    pag_node = soup.select_one('[data-pagination-paginate-path-value]')
    if not pag_node:
        return extract_reviews_diplomeo(soup, url, *parse_etablissement_ville_diplomeo(url))

    paginate_path = pag_node.get("data-pagination-paginate-path-value")
    page_param = pag_node.get("data-pagination-page-parameter-value") or "page"
    max_value  = pag_node.get("data-pagination-page-max-value") or 50
    try:
        max_value = int(max_value)
    except Exception:
        max_value = 50

    etab, ville = parse_etablissement_ville_diplomeo(url)
    all_reviews = []
    for p in range(1, max_value + 1):
        page_url = set_query_param(urljoin(url, paginate_path), page_param, p)
        rr = s.get(page_url, timeout=20)
        if rr.status_code != 200:
            break
        page_soup = BeautifulSoup(rr.text, "html.parser")
        chunk = extract_reviews_diplomeo(page_soup, url, etab, ville)
        if not chunk:
            break
        all_reviews.extend(chunk)
    return all_reviews

# === CAPITAINE STUDY ===
def extract_etab_ville_capstudy(soup):
    h1 = soup.select_one("h1.case27-primary-text")
    txt = clean(h1.get_text()) if h1 else ""
    if txt:
        parts = txt.split()
        etab = normalize_ecole(parts[0].lower())
        ville = " ".join(parts[1:]).lower()
        return etab, ville
    return "", ""

def extract_reviews_capstudy(soup, url):
    reviews, current_review = [], None
    etab, ville = extract_etab_ville_capstudy(soup)
    for bloc in soup.select("li.comment"):
        classes = set(bloc.get("class", []))
        is_reply = "reply" in classes or bloc.find_parent("ul", class_="replies")
        texte = clean(" ".join(p.get_text(" ", strip=True) for p in bloc.select("div.comment-body p")))

        if is_reply:
            if current_review and texte:
                for i in range(1, 4):
                    if not current_review.get(f"reponse_{i}"):
                        current_review[f"reponse_{i}"] = texte
                        break
            continue

        prenom = clean(bloc.select_one("h5.case27-secondary-text").get_text()) if bloc.select_one("h5.case27-secondary-text") else ""
        date_rel = clean(bloc.select_one("span.comment-date").get_text()) if bloc.select_one("span.comment-date") else ""
        annees = re.findall(r"\b(\d{4})\b", date_rel)
        annee = ", ".join(annees) if annees else ""
        note_val = 0.0
        for i in bloc.select("div.listing-rating i, div.listing-review-rating i"):
            classes = set(i.get("class", []))
            if "star_half" in classes:
                note_val += 0.5
            elif "star" in classes and "star_border" not in classes:
                note_val += 1.0
        note = "pas de note" if note_val == 0 else str(note_val)

        current_review = {
            "uid": compute_uid("web", url, prenom, texte),
            "prenom": prenom, "note": note, "date": date_rel, "annee": annee,
            "formation": "", "texte": texte,
            "url": url, "etablissement": normalize_ecole(etab), "ville": ville,
            "reponse_1": "", "reponse_2": "", "reponse_3": "", "site": "capitainestudy"
        }
        reviews.append(current_review)
    return reviews

def scrape_capstudy(url):
    s = requests.Session()
    s.headers.update(HEADERS)
    page, all_reviews, seen = 1, [], set()
    while True:
        u = url if page == 1 else set_query_param(url, "page", page)
        r = s.get(u, timeout=20)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        reviews = extract_reviews_capstudy(soup, url)
        new_count = 0
        for r in reviews:
            if r["uid"] in seen:
                continue
            seen.add(r["uid"])
            all_reviews.append(r)
            new_count += 1
        if new_count == 0:
            break
        page += 1
        time.sleep(1)
    return all_reviews

# === CUSTPLACE ===
def parse_etab_ville_cust(url):
    try:
        path = urlparse(url).path.lower()
        m = re.search(r"/([a-z0-9\-]+)", path)
        if m:
            segment = m.group(1)
            etab = segment.split("-")[0]
            return normalize_ecole(etab), ""
    except Exception:
        pass
    return "", ""

def resolve_etab_ville(url):
    if url in URL_OVERRIDES:
        etab, ville = URL_OVERRIDES[url]
        return normalize_ecole(etab), ville.lower()
    etab, ville = parse_etab_ville_cust(url)
    if not etab or etab == "ecole":
        etab = detect_etab_from_url(url)
    if not ville:
        ville = detect_city_from_url(url)
    return normalize_ecole(etab), (ville or "").lower()

def extract_reviews_cust(soup, url, etab, ville):
    reviews = []
    blocs = soup.select("article[data-view^='message']")
    for bloc in blocs:
        note, texte, prenom, date_rel, annee = "", "", "", "", ""
        note_tag = bloc.select_one("div.aggregateRating")
        if note_tag:
            m = re.search(r"s-(\d+)", " ".join(note_tag.get("class", [])))
            if m:
                note = m.group(1)
        txt_tag = bloc.select_one("p.mb-3")
        if txt_tag:
            texte = clean(txt_tag.get_text(" ", strip=True))
        prenom_tag = bloc.select_one("span.opacity-60")
        if prenom_tag:
            prenom = clean(prenom_tag.get_text()).replace("Par ", "")
        date_tag = bloc.find("span", string=lambda x: x and "expérience" in x.lower())
        if date_tag:
            date_rel = clean(date_tag.get_text())
            m = re.search(r"(\d{4})", date_rel)
            if m:
                annee = m.group(1)
        if prenom or texte:
            reviews.append({
                "uid": compute_uid("web", url, prenom, texte),
                "prenom": prenom, "note": note if note else "pas de note",
                "date": date_rel, "annee": annee, "formation": "",
                "texte": texte, "url": url, "etablissement": normalize_ecole(etab), "ville": ville,
                "reponse_1": "", "reponse_2": "", "reponse_3": "", "site": "custplace"
            })
    return reviews

def scrape_cust(url):
    s = requests.Session()
    s.headers.update({**HEADERS, "Connection": "keep-alive"})
    etab, ville = resolve_etab_ville(url)
    page, all_reviews, seen = 1, [], set()
    while True:
        u = url if page == 1 else set_query_param(url, "page", page)
        r = s.get(u, timeout=30)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        reviews = extract_reviews_cust(soup, url, etab, ville)
        new_count = 0
        for r in reviews:
            if r["uid"] in seen:
                continue
            seen.add(r["uid"])
            all_reviews.append(r)
            new_count += 1
        if new_count == 0:
            break
        page += 1
        time.sleep(1.5 + random.random())
    return all_reviews

# === CHARGEMENT YAML ===
def _load_yaml():
    for fn in YAML_FILES:
        if os.path.exists(fn):
            with open(fn, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("Aucun fichier YAML trouvé (ecole.yaml / ecoles.yaml).")

# === Sélection des écoles (filtre) ===
def _select_ecoles(ECOLES: dict, school_filter=None, ecoles_choisies=None):
    """
    Retourne la liste des clés d'écoles à traiter.
    - school_filter : string (ex: 'EFAP', 'ECOLE BLEU', 'TOUTES' ou None)
    - ecoles_choisies : liste de clés (compatibilité ancienne)
    """
    keys = list(ECOLES.keys())

    # Compat ancienne : si liste explicite fournie, on l'utilise
    if ecoles_choisies:
        return [k for k in keys if k in ecoles_choisies]

    # Nouveau : filtre unique depuis le launcher
    if school_filter and school_filter.upper() != "TOUTES":
        target = school_filter.strip().lower()
        # match case-insensitive sur la clé
        selected = [k for k in keys if k.strip().lower() == target]
        return selected

    # Par défaut : toutes
    return keys

# === MAIN (pour launcher) ===
def run(logger=print, school_filter=None, ecoles_choisies=None):
    cfg = _load_yaml()
    ECOLES = cfg["ecoles"]

    selected_keys = _select_ecoles(ECOLES, school_filter=school_filter, ecoles_choisies=ecoles_choisies)
    if not selected_keys:
        logger(f"⚠️ Aucune école sélectionnée pour le filtre: {school_filter!r}")
        return

    logger(f"🎯 Filtre école: {school_filter or 'TOUTES'}  |  Écoles traitées: {', '.join(selected_keys)}")

    for ecole in selected_keys:
        block = ECOLES[ecole] or {}
        sheet_id = block.get("sheet_id", "").strip()
        urls = block.get("urls", []) or []

        if not sheet_id or not urls:
            logger(f"⚠️ Bloc ignoré ({ecole}) — sheet_id ou urls manquants.")
            continue

        logger(f"\n📚 Collecte pour {ecole}…")

        # --- Préparer le sheet & les index existants
        sheet = get_sheet(sheet_id)
        ensure_headers(sheet)
        header = sheet.row_values(1)
        col_index = {name: header.index(name) + 1 for name in EXPECTED_HEADERS}  # 1-based

        existing_uid = set()      # uids exacts (incluant l'URL)
        existing_soft = {}        # soft_key(site, prenom, texte) -> info(row, date, annee)

        try:
            rows = sheet.get_all_records()
            for i, row in enumerate(rows, start=2):  # data commence à la ligne 2
                uid_val = str(row.get("uid", "")).strip()
                if uid_val:
                    existing_uid.add(uid_val)

                sk = soft_key_from_values(row.get("site", ""), row.get("prenom", ""), row.get("texte", ""))
                if sk:
                    existing_soft[sk] = {
                        "row": i,
                        "date": row.get("date", "") or "",
                        "annee": row.get("annee", "") or "",
                    }
        except Exception:
            pass

        # Ces deux listes seront envoyées au sheet APRES toutes les URLs
        pending_updates = []   # batch_update payloads {range, values}
        pending_new_rows = []  # lignes complètes à append

        # Totaux par école
        total_found, total_new, total_updated = 0, 0, 0

        # ➜ Uniques DU RUN (dédoublonnés via soft-key site+prenom+texte)
        run_soft_seen = set()

        for i, url in enumerate(urls, start=1):
            # ✅ Progress avant traitement de l'URL
            logger(f"PROGRESS {i}/{len(urls)}")
            # 1) scrape l'URL
            reviews = []
            try:
                if "diplomeo.com" in url:
                    reviews = scrape_diplomeo(url)
                elif "capitainestudy" in url:
                    reviews = scrape_capstudy(url)
                elif "custplace" in url:
                    reviews = scrape_cust(url)
                else:
                    reviews = []
            except Exception as e:
                logger(f"🌍 {url} → ⚠️ erreur: {e}")
                continue

            # 2) dédoublonne localement (au cas où la page ait des duplicats)
            uniq_url, seen_local = [], set()
            for r in reviews:
                if r["uid"] in seen_local:
                    continue
                seen_local.add(r["uid"])
                uniq_url.append(r)

            found = len(uniq_url)
            new_here, updated_here = 0, 0

            # 3) décide : nouveau / mise à jour / ignoré
            for r in uniq_url:
                sk = soft_key_from_values(r.get("site", ""), r.get("prenom", ""), r.get("texte", ""))
                if sk not in run_soft_seen:
                        run_soft_seen.add(sk)

                # si l'UID exact existe déjà, on ignore (même source exacte)
                if r["uid"] in existing_uid:
                    continue

                sk = soft_key_from_values(r.get("site", ""), r.get("prenom", ""), r.get("texte", ""))

                # existe déjà via soft-key → possible MAJ date/année
                if sk in existing_soft:
                    info = existing_soft[sk]
                    new_date  = r.get("date", "") or ""
                    new_annee = r.get("annee", "") or ""
                    if new_date != info["date"] or new_annee != info["annee"]:
                        rownum = info["row"]
                        if rownum:
                            pending_updates.append({
                                "range": rowcol_to_a1(rownum, col_index["date"]),
                                "values": [[new_date]],
                            })
                            pending_updates.append({
                                "range": rowcol_to_a1(rownum, col_index["annee"]),
                                "values": [[new_annee]],
                            })
                            updated_here += 1
                            # garder en mémoire la dernière valeur pour éviter de re-MAJ
                            existing_soft[sk]["date"] = new_date
                            existing_soft[sk]["annee"] = new_annee
                    # sinon pas de changement
                    continue

                # sinon : c'est un vrai nouveau
                pending_new_rows.append([r.get(k, "") for k in EXPECTED_HEADERS])
                existing_uid.add(r["uid"])
                existing_soft[sk] = {"row": None, "date": r.get("date", "") or "", "annee": r.get("annee", "") or ""}
                new_here += 1

            total_found += found
            total_new += new_here
            total_updated += updated_here

            # 4) LOG **une seule ligne** pour l'URL
            logger(f"🌍 {url} → {found} avis  |  +{new_here} nouveaux, ♻️ {updated_here} MAJ")

        # 5) Appliquer d’abord les MAJ, puis les ajouts
        if pending_updates:
            sheet.batch_update(pending_updates, value_input_option="RAW")
        if pending_new_rows:
            sheet.append_rows(pending_new_rows, value_input_option="RAW")

        # 6) Résumé par école

        # ➜ Uniques DANS CE RUN (cross-plateformes)
        uniques_in_run = len(run_soft_seen)

        # (A) Résumé complet
        logger(
            f"📊 {ecole} → brut {total_found} | écrit sheet {uniques_in_run} | +{total_new} nouveaux | maj +{total_updated}"
        )
