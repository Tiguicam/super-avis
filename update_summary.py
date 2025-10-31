# update_summary.py
# Met à jour la feuille SOMMAIRE avec les moyennes par école
# Compatible TEST + force toutes les colonnes même si vides

import gspread
import yaml
import os
from statistics import mean

# ------------------------------------------------
# CONFIG
# ------------------------------------------------
YAML_FILES = ["ecole.yaml", "ecoles.yaml"]
CREDENTIALS_FILE = "service_account.json"  # compat local / fallback

EXPECTED_SITES = ["diplomeo", "capitainestudy", "custplace", "gmb"]

SUMMARY_HEADER = [
    "Ecole",
    "Moyenne Diplomeo",
    "Moyenne Capita",
    "Moyenne Custp",
    "Moyenne GMB",
    "Moyenne Générale",
]

# ------------------------------------------------
# Auth Sheets (Streamlit + fallback local)
# ------------------------------------------------
def _get_gspread_client():
    """
    - En mode Streamlit : utilise st.secrets["gcp_service_account"]
    - Sinon : lit un fichier service account local (via $GSPREAD_SA_JSON ou CREDENTIALS_FILE)
    """
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    except Exception:
        pass
    cred_path = os.getenv("GSPREAD_SA_JSON", CREDENTIALS_FILE)
    return gspread.service_account(filename=cred_path)

# ------------------------------------------------
# YAML
# ------------------------------------------------
def _load_yaml():
    """Charge le fichier YAML principal."""
    for fn in YAML_FILES:
        if os.path.exists(fn):
            with open(fn, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("❌ Aucun fichier YAML trouvé (ecole.yaml / ecoles.yaml)")

# ------------------------------------------------
# Sheets
# ------------------------------------------------
def get_sheet(sheet_id, tab="TEST"):
    """Retourne un onglet Google Sheet."""
    gc = _get_gspread_client()
    return gc.open_by_key(sheet_id).worksheet(tab)

def get_or_create_summary(sheet_id):
    """Retourne l’onglet SOMMAIRE ou le crée si absent + force l'entête."""
    gc = _get_gspread_client()
    doc = gc.open_by_key(sheet_id)

    try:
        ws = doc.worksheet("Sommaire")
    except gspread.exceptions.WorksheetNotFound:
        ws = doc.add_worksheet("Sommaire", rows=200, cols=10)

    # Vérifie entête
    header = ws.row_values(1)
    if header != SUMMARY_HEADER:
        ws.update("A1:F1", [SUMMARY_HEADER])

    return ws

# ------------------------------------------------
# Calculs
# ------------------------------------------------
def compute_means(rows):
    """Calcule les moyennes par plateforme.
       rows = [{"note": "...", "site": "..."}]
    """
    def safe_float(v):
        try:
            v = str(v).replace(",", ".")
            return float(v)
        except:
            return None

    scores = {k: [] for k in EXPECTED_SITES}

    for r in rows:
        site = str(r.get("site", "")).lower()
        note = safe_float(r.get("note", ""))

        if note is not None and site in scores:
            scores[site].append(note)

    # Moyenne par site
    res = {}
    for k, arr in scores.items():
        res[k] = round(mean(arr), 2) if arr else ""

    # Moyenne générale
    all_notes = []
    for arr in scores.values():
        all_notes += arr

    res["general"] = round(mean(all_notes), 2) if all_notes else ""

    return res

# ------------------------------------------------
# Mise à jour d’une ligne SOMMAIRE
# ------------------------------------------------
def update_row(ws, row, ecole, means):
    """Met à jour une ligne (force toutes colonnes)."""
    ws.update(
        f"A{row}:F{row}",
        [[
            ecole,
            means.get("diplomeo", ""),
            means.get("capitainestudy", ""),
            means.get("custplace", ""),
            means.get("gmb", ""),
            means.get("general", ""),
        ]]
    )

# ------------------------------------------------
# Main
# ------------------------------------------------
def run(logger=print, school_filter=None):
    """Mise à jour globale."""
    cfg = _load_yaml()
    ECOLES = cfg["ecoles"]

    logger("🔎 Mise à jour du SOMMAIRE…")

    for ecole, block in ECOLES.items():

        sheet_id = block.get("sheet_id", "").strip()
        if not sheet_id:
            logger(f"⚠️ Pas de sheet_id pour {ecole}, ignoré.")
            continue

        if school_filter and school_filter.upper() != "TOUTES":
            if ecole.strip().lower() != school_filter.strip().lower():
                continue

        # Récupération TEST
        try:
            test_ws = get_sheet(sheet_id, "TEST")
        except Exception:
            logger(f"⚠️ {ecole} → feuille TEST introuvable, ignorée.")
            continue

        rows = test_ws.get_all_records()

        means = compute_means(rows)

        sum_ws = get_or_create_summary(sheet_id)

        # Recherche ligne existante
        data = sum_ws.get_all_records()
        found_row = None

        for i, r in enumerate(data, start=2):
            if str(r.get("Ecole", "")).strip().lower() == ecole.strip().lower():
                found_row = i
                break

        # Si absente → nouvelle ligne
        if found_row is None:
            found_row = len(data) + 2

        update_row(sum_ws, found_row, ecole, means)

        logger(f"✅ SOMMAIRE mis à jour pour {ecole}")

    logger("✅ Mise à jour SOMMAIRE — Terminé !")

if __name__ == "__main__":
    run()
