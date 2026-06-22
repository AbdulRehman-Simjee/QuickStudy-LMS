from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, status

from app.utils.files import ensure_dir


def is_supported_youtube_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    if host in {"youtu.be", "www.youtu.be"}:
        return bool(parsed.path.strip("/"))
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            query = parse_qs(parsed.query or "")
            return bool(query.get("v"))
    return False


def download_youtube_video(url: str, save_path: str | Path) -> tuple[str, str, str, int]:
    """
    Download a YouTube video into save_path and return:
    (filename, file_path, title, file_size)
    """

    if not is_supported_youtube_url(url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid YouTube URL")

    try:
        from yt_dlp import YoutubeDL  # type: ignore
        from yt_dlp.utils import DownloadError  # type: ignore
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="yt-dlp is not installed on the server.",
        ) from exc

    target_dir = Path(save_path)
    ensure_dir(target_dir)

    ydl_opts = {
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path_raw = ydl.prepare_filename(info)
            file_path_obj = Path(file_path_raw)
            if not file_path_obj.exists():
                alt = file_path_obj.with_suffix(".mp4")
                if alt.exists():
                    file_path_obj = alt
                else:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Download completed but file not found on disk.",
                    )
    except DownloadError as exc:
        message = str(exc).lower()
        if "private" in message or "unavailable" in message or "not available" in message:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="YouTube video is unavailable") from exc
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to download YouTube video") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to download YouTube video") from exc

    title = (info.get("title") or "").strip() or "YouTube Video"
    file_size = file_path_obj.stat().st_size
    return file_path_obj.name, file_path_obj.as_posix(), title, file_size
