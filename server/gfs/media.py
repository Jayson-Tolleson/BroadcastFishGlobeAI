from __future__ import annotations

from pathlib import Path


class LocationMediaStore:
    def __init__(self, *, data_dir: Path, media_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.media_dir = Path(media_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
