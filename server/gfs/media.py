from __future__ import annotations

from server.gfs_service import GFSService


class LocationMediaStore(GFSService):
    def __init__(self, data_dir=None, media_dir=None):
        # GFSService expects the static root. Infer it from .../static/data and .../static/fishvid.
        static_dir = "static"
        if data_dir is not None:
            try:
                static_dir = str(data_dir.parent)
            except Exception:
                static_dir = "static"
        super().__init__(static_dir)
        if data_dir is not None:
            self.data_dir = data_dir
            self.store_path = self.data_dir / "gfs_location_store.json"
            self.data_dir.mkdir(parents=True, exist_ok=True)
        if media_dir is not None:
            self.fishvid_dir = media_dir
            self.fishvid_dir.mkdir(parents=True, exist_ok=True)
