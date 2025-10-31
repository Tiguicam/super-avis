# dedupe_web.py
# Déduplication dans l'onglet TEST
# Clé: (site, prenom, texte) -> on garde la 1re occurrence
# - Met à jour date/année sur la 1re occurrence si un doublon apporte une valeur différente/non vide
# - Supprime les doublons en BATCH (groupes contigus) pour éviter le quota 429

import os, yaml, re, time
import gspread
from gspread.exceptions import APIError
from gspread.utils import rowcol_to_a1

CREDENTIALS_FILE = "service_account.json"
YAML_FILES = ["ecole.yaml", "ecoles.yaml"]

# ------------ Utils ------------
def clean(t):
    return re.sub(r"\s+"," ", (t or "")).strip()

def detect_site(url: str) -> str:
    u = (url or "").lower()
    if "custplace" in u: return "custplace"
    if "diplomeo"  in u: return "diplomeo"
    if "capitainestudy" in u or "capitaine" in u: return "capitainestudy"
    return ""

def soft_key(site: str, prenom: str, texte: str) -> str:
    s = clean((site or "").lower())
    p = clean((prenom or "").lower())
    t = clean((texte or "").lower())
    return f"{s}||{p}||{t}"

def load_yaml():
    for fn in YAML_FILES:
        if os.path.exists(fn):
            with open(fn, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("Aucun YAML (ecole.yaml / ecoles.yaml)")

def chunked(iterable, n):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf: 
        yield buf

def retry_batch_update(sh, body, max_retries=3, wait_seconds=65):
    """Appelle Spreadsheet.batch_update avec retry simple si 429."""
    for attempt in range(1, max_retries+1):
        try:
            return sh.batch_update(body)
        except APIError as e:
            if "429" in str(e):
                if attempt == max_retries:
                    raise
                time.sleep(wait_seconds)
            else:
                raise

# ------------ Core ------------
def dedupe_sheet(sheet_id):
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    ws = gc.open_by_key(sheet_id).worksheet("TEST")
    sh = ws.spreadsheet  # pour batch_update (deleteDimension)

    rows = ws.get_all_values()
    if not rows:
        print("Feuille vide.")
        return

    header = rows[0]
    data   = rows[1:]
    idx = {name: i for i, name in enumerate(header)}

    # Colonnes nécessaires
    required = ["prenom","texte","url"]
    for col in required:
        if col not in idx:
            raise RuntimeError(f"Colonne manquante: {col}")

    has_site  = "site"  in idx
    has_date  = "date"  in idx
    has_annee = "annee" in idx

    seen = {}          # sk -> {"row": rownum, "date":..., "annee":...}
    to_delete = []     # row numbers (2-based)
    updates   = []     # simple cell updates (dates/annees)
    updated_count = 0

    # Parcours des lignes
    for i, row in enumerate(data, start=2):  # 2..N (1 = header)
        url   = row[idx["url"]]
        site  = row[idx["site"]] if has_site else ""
        if not site:
            site = detect_site(url)

        prenom = row[idx["prenom"]]
        texte  = row[idx["texte"]]
        sk = soft_key(site, prenom, texte)
        if not sk.strip():
            continue

        date_val  = row[idx["date"]]  if has_date  else ""
        annee_val = row[idx["annee"]] if has_annee else ""

        if sk in seen:
            # doublon -> MAJ éventuelle de la 1re occurrence
            first = seen[sk]
            tgt_row = first["row"]

            if has_date:
                old_date = first.get("date","") or ""
                new_date = date_val or ""
                if new_date and new_date != old_date:
                    updates.append({
                        "range": rowcol_to_a1(tgt_row, idx["date"]+1),
                        "values": [[new_date]],
                    })
                    first["date"] = new_date
                    updated_count += 1

            if has_annee:
                old_annee = first.get("annee","") or ""
                new_annee = annee_val or ""
                if new_annee and new_annee != old_annee:
                    updates.append({
                        "range": rowcol_to_a1(tgt_row, idx["annee"]+1),
                        "values": [[new_annee]],
                    })
                    first["annee"] = new_annee
                    updated_count += 1

            to_delete.append(i)
        else:
            seen[sk] = {"row": i, "date": date_val, "annee": annee_val}

    # 1) Appliquer d'abord les MAJ (dates/années) — petit volume
    if updates:
        ws.batch_update(updates)

    # 2) Supprimer les doublons en BATCH, par plages contiguës
    if not to_delete:
        print("✅ Aucun doublon trouvé.")
    else:
        # trier et regrouper en intervalles contigus (2-based)
        to_delete_sorted = sorted(to_delete)
        ranges = []
        start = prev = to_delete_sorted[0]
        for r in to_delete_sorted[1:]:
            if r == prev + 1:
                prev = r
                continue
            ranges.append((start, prev))
            start = prev = r
        ranges.append((start, prev))

        # convertir en deleteDimension (0-based, end exclusive)
        # ATTENTION: on doit envoyer les requêtes en ordre décroissant de startIndex
        # pour ne pas décaler les indices pendant l’exécution.
        requests = []
        for (r1, r2) in sorted(ranges, key=lambda x: x[0], reverse=True):
            start_index = r1 - 1  # data commence ligne 2 => header = 0, data[0] = 1
            end_index   = r2      # exclusif
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "ROWS",
                        "startIndex": start_index,
                        "endIndex": end_index
                    }
                }
            })

        # Pour éviter 429: on découpe en paquets (ex: 50 requêtes/paquet)
        total_deleted = 0
        for req_chunk in chunked(requests, 50):
            retry_batch_update(sh, {"requests": req_chunk})
            # somme des lignes supprimées dans ce chunk
            for req in req_chunk:
                start_i = req["deleteDimension"]["range"]["startIndex"]
                end_i   = req["deleteDimension"]["range"]["endIndex"]
                total_deleted += (end_i - start_i)

        print(f"🧹 {total_deleted} ligne(s) supprimée(s) (doublons).")

    if updated_count:
        print(f"♻️ {updated_count} valeur(s) mise(s) à jour (date/année).")

def main():
    cfg = load_yaml()
    ECOLES = cfg["ecoles"]
    total = 0
    for name, conf in ECOLES.items():
        print(f"\n➡️  Dédup {name}")
        dedupe_sheet(conf["sheet_id"])
        total += 1
    print(f"\n✅ Nettoyage terminé pour {total} feuille(s).")

if __name__ == "__main__":
    main()
