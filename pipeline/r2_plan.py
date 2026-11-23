"""R2 sync PLAN for the bulk data (W1 staging prep, dev23; docs/specs/hosting-seo.md "R2 sync").

    python -m pipeline r2-plan --data build/data [--prev manifest.json] [--write-manifest manifest.json] [--limit 15]

PRINTS what a sync of the bulk folders (config r2.prefixes, default `points`) to a Cloudflare R2 bucket would do: which objects to PUT, which to skip (same content hash as the previous
manifest) and which to DELETE, the totals, the operation count against R2's free tier, and the files that would leave the static-host bundle. It NEVER uploads, never reads a credential and
never contacts a network: there is no upload code in this repository yet (the owner builds the sync step at W1, with a scoped token stored as a GitHub Actions secret). `r2.enabled` (false)
only changes the header the plan prints. Bucket name, account and domain are "set by owner"; nothing here names one.

Pure functions (scan / make_plan / render) are tested offline (tests/test_r2_plan.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

JSON_CACHE = "public, max-age=60"                     # short for JSON (spec: points refresh every few hours, the page must not show day-old data)
HOST_MAX_FILES, HOST_MAX_BYTES = 20_000, 25 * 1024 * 1024     # static-host limits (PLAN rule 6)
R2_CLASS_A_PER_MONTH = 1_000_000                      # free tier (spec: [verify])
CONTENT_TYPES = {".json": "application/json", ".geojson": "application/geo+json", ".png": "image/png", ".txt": "text/plain"}


def settings(cfg: dict) -> dict:
    r2 = (cfg or {}).get("r2") or {}
    return {"enabled": bool(r2.get("enabled")), "bucket": str(r2.get("bucket") or ""), "prefixes": [str(p).strip("/") for p in (r2.get("prefixes") or ["points"])],
            "key_prefix": str(r2.get("key_prefix") if r2.get("key_prefix") is not None else "data/")}


def scan(data_dir: Path, prefixes: list[str], key_prefix: str = "data/") -> list[dict]:
    """every file under data_dir/<prefix> -> {key, path, size, sha1, content_type}, sorted by key. Keys are POSIX paths below key_prefix."""
    out = []
    data_dir = Path(data_dir)
    for pre in prefixes:
        root = data_dir / pre
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                raw = p.read_bytes()
                out.append({"key": key_prefix + p.relative_to(data_dir).as_posix(), "path": p.as_posix(), "size": len(raw), "sha1": hashlib.sha1(raw).hexdigest(),
                            "content_type": CONTENT_TYPES.get(p.suffix.lower(), "application/octet-stream")})
    return sorted(out, key=lambda f: f["key"])


def make_plan(local: list[dict], prev: dict[str, str] | None) -> dict:
    """prev = {key: sha1} of the last sync (None = nothing synced yet). -> {put, skip, delete} (lists of keys) plus byte totals"""
    prev_map = prev or {}
    put = [f for f in local if prev_map.get(f["key"]) != f["sha1"]]
    skip = [f for f in local if prev_map.get(f["key"]) == f["sha1"]]
    gone = sorted(set(prev_map) - {f["key"] for f in local})
    return {"put": put, "skip": skip, "delete": gone, "put_bytes": sum(f["size"] for f in put), "total_bytes": sum(f["size"] for f in local),
            "first_sync": prev is None}


def warnings(local: list[dict]) -> list[str]:
    w = []
    big = [f for f in local if f["size"] > HOST_MAX_BYTES]
    if big:
        w.append(f"{len(big)} file(s) over 25 MiB (static hosts refuse them; R2 would take them): {big[0]['key']}")
    return w


def render(plan: dict, cfg_r2: dict, local: list[dict], limit: int = 15, runs_per_month: int = 4 * 30) -> str:
    """the human-readable plan"""
    put, skip, delete = plan["put"], plan["skip"], plan["delete"]
    mb = lambda n: f"{n / 1e6:.1f} MB"  # noqa: E731
    lines = [f"R2 sync PLAN ({'r2.enabled=true in config, but' if cfg_r2['enabled'] else 'r2.enabled=false:'} this command only prints; nothing is uploaded, no credential is read, no network is used)",
             f"bucket: {cfg_r2['bucket'] or '<set by owner at W1>'}   folders: {', '.join(cfg_r2['prefixes'])}   key prefix: {cfg_r2['key_prefix']!r}",
             f"local files: {len(local):,} ({mb(plan['total_bytes'])}); {'first sync: everything is new' if plan['first_sync'] else 'compared with the previous manifest'}",
             f"PUT {len(put):,} ({mb(plan['put_bytes'])}) | skip {len(skip):,} (same hash) | DELETE {len(delete):,}"]
    for f in put[:limit]:
        lines.append(f"  PUT {f['key']}  {f['size']:,} B  {f['content_type']}  Cache-Control: {JSON_CACHE if f['content_type'].endswith('json') else 'public, max-age=3600'}")
    if len(put) > limit:
        lines.append(f"  ... and {len(put) - limit:,} more PUTs")
    for k in delete[:limit]:
        lines.append(f"  DELETE {k}")
    if len(delete) > limit:
        lines.append(f"  ... and {len(delete) - limit:,} more DELETEs")
    ops = (len(put) + len(delete)) * 1
    lines.append(f"R2 Class A operations this run: {ops:,}; a full upload every 6 h would be {len(local) * runs_per_month:,}/month against a {R2_CLASS_A_PER_MONTH:,}/month free tier "
                 f"(hash-skip makes the real number the PUT count of each run) [verify the free tier at W1]")
    lines.append(f"static-host bundle effect: these {len(local):,} files ({mb(plan['total_bytes'])}) would leave the deployed site (limits {HOST_MAX_FILES:,} files, 25 MiB per file); "
                 "the browser would then need a data origin (docs/specs/hosting-seo.md DATA_ORIGIN), which is NOT implemented")
    lines += [f"WARNING: {w}" for w in warnings(local)]
    return "\n".join(lines)


def run(cfg: dict, data_dir: Path, prev_path: Path | None = None, manifest_out: Path | None = None, limit: int = 15) -> int:
    s = settings(cfg)
    local = scan(data_dir, s["prefixes"], s["key_prefix"])
    prev = None
    if prev_path and Path(prev_path).exists():
        prev = {k: v for k, v in (json.loads(Path(prev_path).read_text(encoding="utf-8")).get("objects") or {}).items()}
    plan = make_plan(local, prev)
    print(render(plan, s, local, limit))
    if manifest_out:                                               # the manifest a FUTURE sync would store after a successful run; writing it here changes nothing remote
        Path(manifest_out).write_text(json.dumps({"objects": {f["key"]: f["sha1"] for f in local}}, indent=1), encoding="utf-8")
        print(f"manifest of the local files written to {manifest_out} (a plan input, not a record of an upload)")
    return 0
