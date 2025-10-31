# -*- coding: utf-8 -*-
"""
Launcher unifié
→ 3 actions
- Choisir une école
- Scraper plateformes web  (script_web.run)
- Avis Google Business      (gmb.run)

⚠️ IMPORTANT
- NE lance PAS les scripts via subprocess
- Capture les print() et les stream dans la même UI
- Pas d’ouverture de fenêtre secondaire

Fichiers à mettre au même niveau :
- launcher.py
- script_web.py
- gmb.py
- gmb.yaml
- service_account.json
- client_secret.json
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from update_summary import run as run_summary


# --------------------------------------------------------------------
# IMPORT SCRIPTS
# --------------------------------------------------------------------
try:
    import script_web
except:
    script_web = None

try:
    import gmb
except:
    gmb = None


# --------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------
class LauncherApp:
    def __init__(self, root):
        self.root = root
        root.title("Extract Avis – Launcher")
        root.geometry("950x680")

        # TOP
        header = ttk.Frame(root)
        header.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(header, text="Extraction des avis", font=("Segoe UI", 16, "bold")).pack(side="left")

        # SELECTION ECOLE
        selection_frame = ttk.Frame(root)
        selection_frame.pack(fill="x", padx=10, pady=(5, 3))

        ttk.Label(selection_frame, text="École :").pack(side="left", padx=(0, 8))

        self.school_var = tk.StringVar()
        self.school_combo = ttk.Combobox(
            selection_frame,
            textvariable=self.school_var,
            state="readonly",
            width=35
        )
        self.school_combo['values'] = [
            "TOUTES",
            "BRASSART",
            "CREAD",
            "EFAP",
            "EFJ",
            "ESEC",
            "ICART",
            "Ecole bleue"
        ]
        self.school_combo.current(0)
        self.school_combo.pack(side="left", padx=(0, 8))

        # BUTTONS
        btns = ttk.Frame(root)
        btns.pack(fill="x", padx=10, pady=6)

        self.btn_web = ttk.Button(btns, text="Scraper plateformes web", command=self.run_web)
        self.btn_web.pack(side="left", padx=(0, 8))

        self.btn_gmb = ttk.Button(btns, text="Avis Google Business (GMB)", command=self.run_gmb)
        self.btn_gmb.pack(side="left", padx=(0, 8))

        self.btn_clear = ttk.Button(btns, text="Effacer les logs", command=self.clear_logs)
        self.btn_clear.pack(side="right")

        self.btn_summary = ttk.Button(btns, text="Mettre à jour Sommaire", command=self.run_summary)
        self.btn_summary.pack(side="left", padx=(0, 8))


        # LOG TEXT
        log_frame = ttk.Frame(root)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.txt = tk.Text(log_frame, wrap="word", height=22, font=("Consolas", 10))
        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=yscroll.set)

        self.txt.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # STATUS BAR
        status_bar = ttk.Frame(root)
        status_bar.pack(fill="x", padx=10, pady=(0,10))
        self.status_var = tk.StringVar(value="Prêt.")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left")

    # ---------------------------------------------------
    def log(self, msg):
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")

    def clear_logs(self):
        self.txt.delete("1.0", "end")

    def set_status(self, s):
        self.status_var.set(s)
        self.root.update_idletasks()

    def _disable_all(self):
        self.btn_web.config(state="disabled")
        self.btn_gmb.config(state="disabled")

    def _enable_all(self):
        self.btn_web.config(state="normal")
        self.btn_gmb.config(state="normal")

    def run_summary(self):
        try:
           self._launch_run("Mise à jour Sommaire", lambda logger: run_summary(logger=logger, school_filter=self.school_var.get()))
        except Exception as e:
           self.log(f"❌ Erreur Sommaire : {e}")
    

    # ===================================================
    # RUN WEB
    # ===================================================
    def run_web(self):
        if script_web is None:
            messagebox.showerror("Erreur", "script_web.py introuvable ⚠️")
            return

        selected = self.school_var.get().strip()
        if not selected:
            messagebox.showwarning("Choix requis", "Sélectionne une école d’abord")
            return

        label = f"Scraper Web – {selected}"

        def runner(logger):
            try:
                if selected == "TOUTES":
                    return script_web.run(logger=logger, school_filter=None)
                else:
                    return script_web.run(logger=logger, school_filter=selected)
            except TypeError:
                # fallback si ton script_web ne supporte pas encore school_filter
                logger("⚠️ script_web.run() ne supporte pas 'school_filter'. Ajoute-le dans script_web.py.")
                return script_web.run(logger=logger)

        self._launch_run(label, runner)

    # ===================================================
    # RUN GMB
    # ===================================================
    def run_gmb(self):
        if gmb is None:
            messagebox.showerror("Erreur", "gmb.py introuvable ⚠️")
            return

        selected = self.school_var.get().strip()
        if not selected:
            messagebox.showwarning("Choix requis", "Sélectionne une école d’abord")
            return

        label = f"GMB – {selected}"

        def runner(logger):
            if selected == "TOUTES":
                return gmb.run(logger=logger, school_filter=None)
            else:
                return gmb.run(logger=logger, school_filter=selected)

        self._launch_run(label, runner)

    # ===================================================
    def _launch_run(self, label, func):
        self.clear_logs()
        self._disable_all()
        self.set_status(f"{label} — démarrage…")
        self.log(f"▶️ {label} lancé…")

        # Run in background thread
        def worker():
            try:
                func(self.log)   # <— CAPTURE PRINTS
                self.log("✅ Terminé.")
                self.set_status(f"{label} — Terminé ✔")
            except Exception as e:
                self.log(f"❌ Exception : {e}")
                self.set_status(f"{label} — Erreur ⚠️")
            finally:
                self._enable_all()

        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------
def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
