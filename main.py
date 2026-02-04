import re
import time
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import config

# Merkt sich zuletzt verarbeitete Dateien (Windows kann Events doppelt feuern)
PROCESSED_AT = {}  # path -> timestamp
DEDUP_SECONDS = 15


# Beispiel: WhatsApp Audio 2026-02-03 at 21.34.20.aac
WHATSAPP_RE = re.compile(r"^WhatsApp Audio (\d{4}-\d{2}-\d{2}) at .*", re.IGNORECASE)


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


@dataclass
class NamingInput:
    title: str
    tag: str  # optional (T1/T2/Backing/1/2/...)


def prompt_naming(date_str: str, original_name: str) -> NamingInput | None:
    """Popup: Titel + optional Tag."""
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    title = simpledialog.askstring(
        "Bandaufnahme – Titel",
        f"WhatsApp-Audio vom {date_str}\n\nTitel eingeben (ohne Datum):\n\nDatei: {original_name}",
        parent=root
    )
    if not title:
        root.destroy()
        return None

    tag = simpledialog.askstring(
        "Bandaufnahme – Optional Tag",
        "Optional Tag (z.B. T1, T2, Backing, 1, 2) oder leer:",
        parent=root
    ) or ""

    root.destroy()
    return NamingInput(title=title.strip(), tag=tag.strip())


def build_filename(title: str, date_str: str, tag: str) -> str:
    title = sanitize(title)
    tag = sanitize(tag) if tag else ""
    base = f"{title}_{date_str}"
    if tag:
        base += f"_{tag}"
    return base + ".mp3"


class Handler(FileSystemEventHandler):
    def on_created(self, event):
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

        date_str = m.group(1)

        if not wait_until_file_is_stable(src):
            print(f"❌ Download nicht fertig: {src.name}")
            return

        info = prompt_naming(date_str, src.name)
        if info is None:
            print(f"↩️ Übersprungen: {src.name}")
            return

        filename = build_filename(info.title, date_str, info.tag)
        dst = next_available(config.DROPBOX_TARGET / filename)

        try:
            convert_to_mp3(src, dst)
            print(f"✅ Konvertiert: {src.name} -> {dst.name}")

            # Originaldatei löschen (verhindert doppeltes Event)
            if getattr(config, "DELETE_ORIGINALS", False):
                try:
                    src.unlink(missing_ok=True)
                except Exception as e:
                    print(f"⚠️ Konnte Original nicht löschen: {e}")


        except subprocess.CalledProcessError:
            print("❌ ffmpeg Fehler – ist ffmpeg installiert und im PATH?")
        except Exception as e:
            print(f"❌ Fehler: {e}")


def main():
    config.DROPBOX_TARGET.mkdir(parents=True, exist_ok=True)
    print(f"Überwache: {config.DOWNLOADS}")
    print(f"Ziel:      {config.DROPBOX_TARGET}")

    observer = Observer()
    observer.schedule(Handler(), str(config.DOWNLOADS), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
