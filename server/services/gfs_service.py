"""Legacy compatibility shim for historical imports.

Authoritative runtime code should import from `server.gfs.engine`/`server.gfs.routes`.
This module remains only to avoid breaking older import paths.
"""

from server.gfs_service import GFSService

__all__ = ["GFSService"]
