from __future__ import annotations

__all__ = ["GfsEngine", "LocationMediaStore", "create_gfs_blueprint", "load_gfs_config"]


def __getattr__(name: str):
    if name == "GfsEngine":
        from server.gfs.engine import GfsEngine
        return GfsEngine
    if name == "LocationMediaStore":
        from server.gfs.media import LocationMediaStore
        return LocationMediaStore
    if name == "create_gfs_blueprint":
        from server.gfs.routes import create_gfs_blueprint
        return create_gfs_blueprint
    if name == "load_gfs_config":
        from server.gfs.config import load_gfs_config
        return load_gfs_config
    raise AttributeError(name)
