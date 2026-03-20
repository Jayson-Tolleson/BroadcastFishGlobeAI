from __future__ import annotations

from pathlib import Path

from quart import Blueprint, jsonify


def create_gfs_blueprint(static_dir: Path) -> Blueprint:
    bp = Blueprint("gfs", __name__, url_prefix="/gfs")
    _ = static_dir

    @bp.get("")
    async def gfs_index():
        return jsonify({"ok": True, "service": "gfs"})

    @bp.get("/api/source-check")
    async def source_check():
        return jsonify(
            {
                "ok": True,
                "sources": ["thredds_gfs", "hycom_ncss", "coastwatch_chlorophyll"],
                "mock_bbox": [-118.6, 32.6, -117.8, 33.4],
            }
        )

    return bp
