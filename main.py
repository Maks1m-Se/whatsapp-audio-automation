import re
import time
import subprocess
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import config

SHUTTING_DOWN = False

UI = {}
CURRENT_FILE = None



# Merkt sich zuletzt verarbeitete Dateien (Windows kann Events doppelt feuern)
PROCESSED_AT = {}  # path -> timestamp
DEDUP_SECONDS = 15


# Beispiel: WhatsApp Audio 2026-02-03 at 21.34.20.aac
WHATSAPP_RE = re.compile(
    r"^WhatsApp (Audio|Ptt) (\d{4}-\d{2}-\d{2}) at .*",
    re.IGNORECASE
)


def create_status_window(on_quit):
    import tkinter as tk

    root = tk.Tk()
    root.title("WhatsApp Audio Automation")
    root.geometry("540x420")
    root.resizable(False, False)

    frame = tk.Frame(root, padx=20, pady=20)
    frame.pack(fill="both", expand=True)

    title = tk.Label(
        frame,
        text="WhatsApp Audio Automation",
        font=("Segoe UI", 14, "bold")
    )
    title.pack(anchor="w", pady=(0, 10))

    status_var = tk.StringVar(value="Warte auf WhatsApp-Audio in Downloads …")

    status_label = tk.Label(
        frame,
        textvariable=status_var,
        fg="#2c7be5",
        wraplength=480,
        justify="left",
        height=4,        # <-- WICHTIG: feste Höhe
        anchor="nw"      # Text bleibt oben
    )
    status_label.pack(anchor="w", pady=(0, 15), fill="x")


    info = tk.Label(
        frame,
        justify="left",
        text=(
            "Ablauf:\n"
            "1. WhatsApp-Audio herunterladen\n"
            "2. Songtitel eingeben\n"
            "3. Optionalen Tag eingeben\n"
            "4. „Konvertieren“ klicken\n\n"
            f"Zielordner:\n{config.DROPBOX_TARGET}"
        )
    )
    info.pack(anchor="w", pady=(0, 15))

    # --- Eingabefelder ---
    form = tk.Frame(frame)
    form.pack(anchor="w", pady=(0, 15))

    tk.Label(form, text="Songtitel:").grid(row=0, column=0, sticky="w")
    title_entry = tk.Entry(form, width=40, state="disabled")
    title_entry.grid(row=0, column=1, padx=10)

    tk.Label(form, text="Optionaler Tag:").grid(row=1, column=0, sticky="w")
    tag_entry = tk.Entry(form, width=40, state="disabled")
    tag_entry.grid(row=1, column=1, padx=10, pady=(5, 0))

    # --- Buttons ---
    btns = tk.Frame(frame)
    btns.pack(fill="x")

    convert_btn = tk.Button(btns, text="Konvertieren", state="disabled", width=15)
    convert_btn.pack(side="left")

    skip_btn = tk.Button(btns, text="Überspringen", state="disabled", width=15)
    skip_btn.pack(side="left", padx=10)

    quit_btn = tk.Button(btns, text="App beenden", command=on_quit, width=15)
    quit_btn.pack(side="right")

    # Alles zurückgeben, was wir später steuern wollen
    return {
        "root": root,
        "status_var": status_var,
        "title_entry": title_entry,
        "tag_entry": tag_entry,
        "convert_btn": convert_btn,
        "skip_btn": skip_btn,
    }


def wait_until_file_is_stable(path: Path, timeout=90, interval=0.4) -> bool:
    start = time.time()
    last_size = -1
    while time.time() - start < timeout:
        if not path.exists():
            time.sleep(interval)
            continue
        size = path.stat().st_size
        if size == last_size and size > 0:
            return True
        last_size = size
        time.sleep(interval)
    return False


def sanitize(s: str) -> str:
    s = s.strip().replace(" ", "_")
    for ch in r'<>:"/\|?*':
        s = s.replace(ch, "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def next_available(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def convert_to_mp3(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.FFMPEG, "-y",
        "-i", str(src),
        "-vn",
        "-codec:a", "libmp3lame",
        "-q:a", str(config.MP3_VBR_QUALITY),
        str(dst)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_filename(title: str, date_str: str, tag: str) -> str:
    title = sanitize(title)
    tag = sanitize(tag) if tag else ""
    base = f"{title}_{date_str}"
    if tag:
        base += f"_{tag}"
    return base + ".mp3"

def activate_ui_for_file(file_info):
    global CURRENT_FILE

    CURRENT_FILE = file_info

    UI["status_var"].set(
        f"Datei erkannt:\n{file_info['name']}\n\n"
        "Bitte Titel, optional Tag eingeben und „Konvertieren“ klicken."
    )

    UI["title_entry"].config(state="normal")
    UI["tag_entry"].config(state="normal")
    UI["convert_btn"].config(state="normal")
    UI["skip_btn"].config(state="normal")

    UI["title_entry"].delete(0, "end")
    UI["tag_entry"].delete(0, "end")

    UI["title_entry"].focus_set()

def reset_ui_to_waiting():
    global CURRENT_FILE
    CURRENT_FILE = None

    UI["status_var"].set("Warte auf WhatsApp-Audio in Downloads …")
    UI["title_entry"].delete(0, "end")
    UI["tag_entry"].delete(0, "end")
    UI["title_entry"].config(state="disabled")
    UI["tag_entry"].config(state="disabled")
    UI["convert_btn"].config(state="disabled")
    UI["skip_btn"].config(state="disabled")

def convert_current():
    global CURRENT_FILE

    if not CURRENT_FILE:
        return

    src: Path = CURRENT_FILE["path"]
    date_str: str = CURRENT_FILE["date"]

    title = UI["title_entry"].get().strip()
    tag = UI["tag_entry"].get().strip()

    if not title:
        UI["status_var"].set("Bitte zuerst einen Songtitel eingeben.")
        UI["title_entry"].focus_set()
        return

    UI["status_var"].set(f"Konvertiere:\n{src.name}\nBitte kurz warten …")
    UI["convert_btn"].config(state="disabled")
    UI["skip_btn"].config(state="disabled")

    try:
        filename = build_filename(title, date_str, tag)
        dst = next_available(config.DROPBOX_TARGET / filename)

        convert_to_mp3(src, dst)

        # Originaldatei löschen (verhindert doppeltes Event)
        if getattr(config, "DELETE_ORIGINALS", False):
            try:
                src.unlink(missing_ok=True)
            except Exception as e:
                print(f"⚠️ Konnte Original nicht löschen: {e}")

        UI["status_var"].set(f"Fertig ✅\n{dst.name}\n\nWarte auf nächste Datei …")
        # kurzer Moment zum Lesen, dann zurücksetzen
        UI["root"].after(1200, reset_ui_to_waiting)

    except subprocess.CalledProcessError:
        UI["status_var"].set("❌ ffmpeg Fehler – ist ffmpeg installiert und im PATH?")
        UI["root"].after(2500, reset_ui_to_waiting)
    except Exception as e:
        UI["status_var"].set(f"❌ Fehler: {e}")
        UI["root"].after(2500, reset_ui_to_waiting)



class Handler(FileSystemEventHandler):
    def on_created(self, event):
        if SHUTTING_DOWN:
            return
        
        if event.is_directory:
            return

        src = Path(event.src_path)

        # Dedup: gleiche Datei innerhalb kurzer Zeit nur einmal behandeln
        now = time.time()
        last = PROCESSED_AT.get(str(src))
        if last and (now - last) < DEDUP_SECONDS:
            return
        PROCESSED_AT[str(src)] = now

        # Dict klein halten
        if len(PROCESSED_AT) > 500:
            # alte Einträge rausschmeißen
            cutoff = now - (DEDUP_SECONDS * 2)
            for k in list(PROCESSED_AT.keys()):
                if PROCESSED_AT[k] < cutoff:
                    del PROCESSED_AT[k]

        # Ignoriere temporäre Downloads
        if src.suffix.lower() == ".crdownload":
            return

        if src.suffix.lower() not in {e.lower() for e in config.AUDIO_EXTS}:
            return

        m = WHATSAPP_RE.match(src.stem)
        if not m:
            return

        date_str = m.group(2)

        if not wait_until_file_is_stable(src):
            print(f"❌ Download nicht fertig: {src.name}")
            return

        root = UI["root"]

        root.after(
            0,
            activate_ui_for_file,
            {
                "path": src,
                "date": date_str,
                "name": src.name,
            }
        )




def main():
    global SHUTTING_DOWN
    observer = None

    # --- Quit-Funktion für Fenster & App ---
    def quit_app():
        global SHUTTING_DOWN
        SHUTTING_DOWN = True
        print("⏹️ Automation wird beendet …")
        if observer is not None:
            observer.stop()

        try:
            root.destroy()
        except Exception:
            pass

    # --- Status-Fenster erstellen ---
    ui = create_status_window(on_quit=quit_app)
    root = ui["root"]
    global UI
    UI = ui



    config.DROPBOX_TARGET.mkdir(parents=True, exist_ok=True)
    print(f"Überwache: {config.DOWNLOADS}")
    print(f"Ziel:      {config.DROPBOX_TARGET}")

    # --- Watchdog starten ---
    observer = Observer()
    observer.schedule(Handler(), str(config.DOWNLOADS), recursive=False)
    observer.start()

    # --- Fenster-Schließen (X) genauso behandeln wie "App beenden" ---
    root.protocol("WM_DELETE_WINDOW", quit_app)


    def skip_current():
        global CURRENT_FILE
        if CURRENT_FILE:
            print(f"↩️ Übersprungen: {CURRENT_FILE['name']}")
            try:
                CURRENT_FILE["path"].unlink(missing_ok=True)
            except Exception:
                pass

        reset_ui_to_waiting()

    
    UI["skip_btn"].config(command=skip_current)
    UI["convert_btn"].config(command=convert_current)

    reset_ui_to_waiting()

    # --- Tkinter Event Loop ---
    try:
        root.mainloop()
    except KeyboardInterrupt:
        quit_app()

    observer.join()




if __name__ == "__main__":
    main()
