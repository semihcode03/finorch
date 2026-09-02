"""Video kare cikarimi (ffmpeg sahne degisimi tespiti).

Teknik analiz videolarinda grafik ekranda degistikce kare alinir. Boylece her
saniyeyi degil, gorsel olarak anlamli anlari yakalariz (maliyet/gurultu dengesi).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from finorch.config import settings

logger = logging.getLogger(__name__)


def _download_video(url: str, out_dir: Path) -> Path | None:
    import yt_dlp

    out_tmpl = str(out_dir / "%(id)s.%(ext)s")
    # Kareler icin dusuk cozunurluk yeterli (hiz + disk tasarrufu)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bv*[height<=480]/b[height<=480]/b",
        "outtmpl": out_tmpl,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        vid = info.get("id")
        for f in out_dir.glob(f"{vid}.*"):
            if f.suffix.lower() in {".mp4", ".mkv", ".webm"}:
                return f
    except Exception as e:
        logger.error("Video indirilemedi (%s): %s", url, e)
    return None


def extract_scene_frames(url: str, external_id: str) -> list[tuple[str, float | None]]:
    """Bir videodan sahne degisimlerinde kareler cikarir.

    Doner: [(kare_dosya_yolu, saniye|None), ...]
    """
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg bulunamadi; kare cikarimi atlaniyor.")
        return []

    settings.ensure_dirs()
    work_dir = settings.frames_dir / external_id
    work_dir.mkdir(parents=True, exist_ok=True)

    video = _download_video(url, work_dir)
    if not video:
        return []

    threshold = settings.yt_frame_scene_threshold
    max_frames = settings.yt_max_frames
    pattern = str(work_dir / "frame_%03d.jpg")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video),
        "-vf", f"select='gt(scene,{threshold})',scale=1280:-1",
        "-vsync", "vfr",
        "-frames:v", str(max_frames),
        pattern,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=1800)
    except Exception as e:
        logger.error("Kare cikarimi hatasi (%s): %s", url, e)
        return []
    finally:
        try:
            video.unlink(missing_ok=True)
        except Exception:
            pass

    frames = sorted(work_dir.glob("frame_*.jpg"))
    # Timestamp'i su asamada hesaplamiyoruz (None); ileride showinfo ile eklenebilir.
    return [(str(f), None) for f in frames]
