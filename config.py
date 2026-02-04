from pathlib import Path

# Quelle: Downloads
DOWNLOADS = Path(r"C:\Users\maksi\Downloads")

# Ziel: Dropbox
DROPBOX_TARGET = Path(r"C:\Users\maksi\Dropbox\Primebeats\Probeaufnahmen")

# ffmpeg (wenn nicht im PATH, hier volle exe setzen)
FFMPEG = "ffmpeg"

# WhatsApp-Audio-Endungen
AUDIO_EXTS = {
    ".aac",
    ".ogg",
    ".opus",
    ".m4a",
    ".mp4",
    ".wav",
    ".webm",
    ".mpeg",
    ".mp3",
}


# Optional: nach erfolgreicher Konvertierung Original archivieren
ARCHIVE_ORIGINALS = False
DELETE_ORIGINALS = True
ARCHIVE_FOLDER = DOWNLOADS / "WhatsApp_Archiv"

# MP3 Qualität (0..9, 0 beste; 2 ist sehr gut)
MP3_VBR_QUALITY = "2"
