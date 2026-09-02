"""Yerel transkripsiyon: yt-dlp ile ses indir, faster-whisper ile metne cevir.

Model, ilk kullanimda ayarlarda belirtilen boyutta (WHISPER_MODEL) indirilir ve
onbellege alinir. VPS icin varsayilan: small + cpu + int8 (hiz/kalite dengesi).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from finorch.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model():
    from faster_whisper import WhisperModel

    logger.info(
        "Whisper modeli yukleniyor: %s (%s / %s)",
        settings.whisper_model,
        settings.whisper_device,
        settings.whisper_compute_type,
    )
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def _download_audio(url: str) -> Path | None:
    import yt_dlp

    settings.ensure_dirs()
    out_tmpl = str(settings.downloads_dir / "%(id)s.%(ext)s")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        vid = info.get("id")
        audio = settings.downloads_dir / f"{vid}.mp3"
        return audio if audio.exists() else None
    except Exception as e:
        logger.error("Ses indirilemedi (%s): %s", url, e)
        return None


def transcribe_url(url: str, language: str = "tr") -> list[dict]:
    """Bir video url'sinden zaman damgali transkript segmentleri uretir.

    Doner: [{"start": float, "end": float, "text": str}, ...]. Basarisizsa bos liste.
    """
    audio = _download_audio(url)
    if not audio:
        return []
    try:
        model = _get_model()
        segments, _info = model.transcribe(str(audio), language=language, vad_filter=True)
        out: list[dict] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        return out
    except Exception as e:
        logger.error("Transkripsiyon hatasi (%s): %s", url, e)
        return []
    finally:
        try:
            audio.unlink(missing_ok=True)
        except Exception:
            pass
