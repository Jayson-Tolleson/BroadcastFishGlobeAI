# Repository sanitation and dedupe notes

## What was preserved
- All runtime source modules under `server/gfs/` were kept intact, including bait, water providers, and intelligence logic.
- Broadcast and watch route codepaths were kept intact (`server/broadcast/`, `server/ws/watch.py`, and frontend route entrypoints in `static/`).

## What was cleaned
- Removed committed Python bytecode caches (`__pycache__/*.pyc`) from server and test directories.
- Removed one backup source artifact (`server/gfs/providers/rtofs.py.bak`).
- Removed one out-of-tree patch duplicate under `mnt/data/.../bait.py`.
- Added a root `.gitignore` to prevent cache/backup/scratch artifacts from being recommitted.
