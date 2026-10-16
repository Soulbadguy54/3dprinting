"""Fail the build if the initially loaded JS bundle regresses noticeably.

The emoji picker and artwork are lazily loaded in separate chunks; they do not
belong in the initial JS budget. Revisit limits based on real-user performance.
"""
from pathlib import Path
import gzip

assets = Path("dist/assets")
chunks = sorted(assets.glob("index-*.js"))
if len(chunks) != 1:
    raise SystemExit(f"Expected one initial index chunk, found {len(chunks)}")
chunk = chunks[0]
raw = chunk.read_bytes()
compressed = gzip.compress(raw, compresslevel=9)
print(f"Initial JS {chunk.name}: {len(raw)/1024:.1f} KiB raw, {len(compressed)/1024:.1f} KiB gzip")
RAW_LIMIT = 550_000
GZIP_LIMIT = 200_000
if len(raw) > RAW_LIMIT or len(compressed) > GZIP_LIMIT:
    raise SystemExit("Bundle exceeded mobile JS budget: inspect code splitting")
