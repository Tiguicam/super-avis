import streamlit as st
import script_web
import gmb
import update_summary
import io
import sys
from datetime import datetime

# ----------------------------------------------------------
# UI de base
# ----------------------------------------------------------
st.set_page_config(page_title="Super Avis", layout="wide")
st.markdown("## 🧾 Super Avis – Interface Web")

# Liste des écoles
ECOLES = [
    "TOUTES",
    "BRASSART",
    "CREAD",
    "EFAP",
    "EFJ",
    "ESEC",
    "ICART",
    "Ecole bleue",
]
selected = st.selectbox("Sélectionne une école :", ECOLES)

# ----------------------------------------------------------
# État & conteneur de logs persistants
# ----------------------------------------------------------
if "logs" not in st.session_state:
    st.session_state.logs = []

logs_box = st.container()

def render_logs():
    if not st.session_state.logs:
        logs_box.info("Aucun log pour le moment.")
        return
    bullets = [f"- `{row['ts']}` {row['msg']}" for row in st.session_state.logs]
    logs_box.markdown("\n".join(bullets))

# ----------------------------------------------------------
# Capture des logs (append + re-render)
# ----------------------------------------------------------
class StreamLogger(io.StringIO):
    def __init__(self, container):
        super().__init__()
        self.container = container

    def write(self, msg: str):
        # Découpe multi-lignes, ignore lignes vides
        for line in msg.splitlines():
            line = line.rstrip()
            if not line:
                continue
            st.session_state.logs.append({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "msg": line
            })
        render_logs()

# ----------------------------------------------------------
# Wrapper pour exécuter et afficher les logs
# ----------------------------------------------------------
def run_with_logs(func):
    # feedback immédiat
    st.session_state.logs.append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": "⏳ En cours…"})
    render_logs()

    buffer = StreamLogger(logs_box)
    old_stdout = sys.stdout
    sys.stdout = buffer
    try:
        func(buffer.write)
        buffer.write("✅ Terminé")
    except Exception as e:
        buffer.write(f"❌ ERREUR : {e}")
    finally:
        sys.stdout = old_stdout

# ----------------------------------------------------------
# Actions sur les logs
# ----------------------------------------------------------
col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("🧹 Effacer les logs"):
        st.session_state.logs = []
        render_logs()

with col_b:
    if st.session_state.logs:
        export_txt = "\n".join(f"[{r['ts']}] {r['msg']}" for r in st.session_state.logs)
        st.download_button("⬇️ Télécharger les logs", data=export_txt, file_name="logs.txt")

# Affichage initial si rien n'a encore été écrit
render_logs()

# ----------------------------------------------------------
# Boutons d'actions
# ----------------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Scraper plateformes web"):
        run_with_logs(lambda logger: script_web.run(logger=logger, school_filter=selected))

with col2:
    if st.button("Avis Google Business"):
        run_with_logs(lambda logger: gmb.run(logger=logger, school_filter=selected))

with col3:
    if st.button("Mettre à jour le Sommaire"):
        run_with_logs(lambda logger: update_summary.run(logger=logger, school_filter=selected))
