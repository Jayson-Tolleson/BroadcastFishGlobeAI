# Repository sanitation and dedupe notes

## What was preserved
- All runtime source modules under `server/gfs/` were kept intact, including bait, water providers, and intelligence logic.
- Broadcast and watch route codepaths were kept intact (`server/broadcast/`, `server/ws/watch.py`, and frontend route entrypoints in `static/`).
- Historical/source snapshot files such as `server/gfs/providers/rtofs.py.bak` and `mnt/data/LFTR_gfs_school_blocks_patch/server/gfs/derive/bait.py` were retained to avoid removing requested source material.

## What was cleaned
- Removed committed Python bytecode caches (`__pycache__/*.pyc`) from server and test directories.
- Added a root `.gitignore` to prevent cache/backup/scratch artifacts from being recommitted in the future.
