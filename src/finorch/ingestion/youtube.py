"""YouTube ingestor (yt-dlp).

Bir kanalin son videolarini listeler. Video icin Turkce altyazi (manuel veya
otomatik) varsa transkript olarak alir; yoksa `needs_transcription=True` isaretler
ve transkripsiyon adimi sesi indirip Whisper ile cikarir.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx

from finorch.ingestion.base import FetchedItem, Ingestor

logger = logging.getLogger(__name__)

_SUB_LANGS = ["tr", "tr-TR", "en"]


def _ts_to_sec(ts: str) -> float:
    """VTT zaman damgasi (HH:MM:SS.mmm) -> saniye."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])
    except ValueError:
        return 0.0


def _vtt_to_segments(vtt: str) -> list[dict]:
    """VTT -> zaman damgali segmentler: [{"start", "end", "text"}]."""
    segments: list[dict] = []
    cur_start: float | None = None
    cur_end: float | None = None
    cur_text: list[str] = []

    def _flush() -> None:
        nonlocal cur_start, cur_end, cur_text
        if cur_start is not None and cur_text:
            text = re.sub(r"<[^>]+>", "", " ".join(cur_text)).strip()
            if text and (not segments or segments[-1]["text"] != text):
                segments.append({"start": cur_start, "end": cur_end, "text": text})
        cur_start, cur_end, cur_text = None, None, []

    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        if "-->" in line:
            _flush()
            left, _, right = line.partition("-->")
            cur_start = _ts_to_sec(left)
            cur_end = _ts_to_sec(right.split()[0]) if right.strip() else None
            continue
        cur_text.append(line)
    _flush()
    return segments


def _segments_to_text(segments: list[dict]) -> str:
    return " ".join(s["text"] for s in segments).strip()


class YouTubeIngestor(Ingestor):
    source_type = "youtube"

    def _ydl_opts(self) -> dict:
        return {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }

    def healthcheck(self) -> tuple[bool, str]:
        try:
            import yt_dlp  # noqa: F401

            return True, "yt-dlp yuklu"
        except Exception as e:  # pragma: no cover
            return False, f"yt-dlp bulunamadi: {e}"

    def _list_recent_video_ids(self, ref: str, limit: int) -> list[str]:
        import yt_dlp

        # Kanalin "videos" sekmesini flat cek
        url = ref.rstrip("/")
        if url.startswith("@"):
            url = f"https://www.youtube.com/{url}"
        if "/videos" not in url and ("youtube.com/@" in url or "youtube.com/channel" in url):
            url = url + "/videos"

        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": limit}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = (info or {}).get("entries") or []
        ids = [e.get("id") for e in entries if e.get("id")]
        return ids[:limit]

    def _fetch_subtitle_segments(self, subs: dict) -> list[dict]:
        for lang in _SUB_LANGS:
            tracks = subs.get(lang)
            if not tracks:
                continue
            # vtt formatini tercih et
            track = next((t for t in tracks if t.get("ext") == "vtt"), tracks[0])
            try:
                resp = httpx.get(track["url"], timeout=30)
                resp.raise_for_status()
                segments = _vtt_to_segments(resp.text)
                if segments:
                    return segments
            except Exception as e:  # pragma: no cover
                logger.warning("Altyazi indirilemedi (%s): %s", lang, e)
        return []

    def fetch(self, ref: str, limit: int = 5) -> list[FetchedItem]:
        import yt_dlp

        items: list[FetchedItem] = []
        try:
            video_ids = self._list_recent_video_ids(ref, limit)
        except Exception as e:
            logger.error("Kanal videolari listelenemedi (%s): %s", ref, e)
            return items

        with yt_dlp.YoutubeDL(self._ydl_opts()) as ydl:
            for vid in video_ids:
                vurl = f"https://www.youtube.com/watch?v={vid}"
                try:
                    info = ydl.extract_info(vurl, download=False)
                except Exception as e:
                    logger.warning("Video bilgisi alinamadi (%s): %s", vid, e)
                    continue

                published_at = None
                if info.get("upload_date"):
                    try:
                        published_at = datetime.strptime(info["upload_date"], "%Y%m%d")
                    except ValueError:
                        pass

                subs = {**(info.get("subtitles") or {}), **(info.get("automatic_captions") or {})}
                segments = self._fetch_subtitle_segments(subs) if subs else []
                transcript = _segments_to_text(segments)

                items.append(
                    FetchedItem(
                        source_type="youtube",
                        external_id=vid,
                        url=vurl,
                        title=info.get("title", ""),
                        transcript=transcript,
                        segments=segments,
                        published_at=published_at,
                        needs_transcription=not transcript,
                        extra={"duration": info.get("duration")},
                    )
                )
        return items
