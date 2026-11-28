# Data ingest to local storage / Cloudflare R2 (`python -m ingester`)

Goal: data retrieval runs on its own and lands in an object store as organized JSON (+ model-map PNGs), so a later API
can serve it to the front end. The website build (`python -m pipeline build`) and the GitHub workflows are unchanged.

## Flow

```
sources (ingester/src/ingester/fetch/, one module per source)  ->  stage folder (data/ + models/)
   -> publish (ingester/src/ingester/publish.py) -> store: local folder (default) or R2; the manifest keeps each source's status
```

- Standalone: the ingester owns its fetch code (`ingester/src/ingester/fetch/`, copies of the website's source modules), its settings (`ingester/config/`) and its point lists (`ingester/data/`). It imports nothing from `pipeline/` and builds no website files (no `meta.json`, search index or catalogs; run status is kept in the store manifest). Copies are kept in step by hand until the website reads from the store.
- Code: `ingester/src/ingester/store.py` (LocalStore, R2Store, credentials), `ingester/src/ingester/publish.py` (scan, plan, upload order, manifest),
  `ingester/src/ingester/sources.py` (registry: what each source runs and which stage paths it owns), `ingester/src/ingester/runner.py` (one run),
  `ingester/src/ingester/__main__.py` (CLI). Tests: `ingester/tests/test_ingest.py` (offline: its own FakeSession copy in `ingester/tests/fakes.py`, plus a fake S3 client).
- Config: `config/settings.yml` `ingest:` (stage_dir, local_store_dir, layout, archive). Credentials are never in config.

## Store layout (identical locally and in R2)

| Key | Content |
|---|---|
| `v1/data/...` | the site's data documents, same names and bytes as `build/data/` (snotel.geojson, snotel/<station>.json, points/<id>.json, alerts/, afd/, ...) |
| `v1/models/...` | model products: ecmwf/, gefs/, <map model>/<cycle>/<field>/<domain>/fNNN.png, index.json |
| `v1/_manifest.json` | `{layout, published_at, sources: {name: last run status}, objects: {key: {sha256, size}}}` |
| `archive/runs/<YYYYMMDDTHHMMSSZ>/...` | optional (`--archive` / `ingest.archive`): copies of the objects that CHANGED in that run |

`v1` is the layout version: a later schema change (e.g. an API-friendly envelope) goes under `v2/` next to it.

## Rules

- **Hash skip:** an object is uploaded only when its sha256 differs from the manifest (R2 Class A operations are budgeted).
- **Order:** payload files, then `index.json` / `summary.json` / `exceed_summary.json`, then `meta.json`, then the manifest.
- **Scope:** a run publishes only the paths its sources own (`Source.writes`) plus the derived files. A persistent
  local stage therefore never pushes another source's stale files over newer ones in the store.
- **Prune** (`--prune`, off by default) deletes stored objects inside the run's scope that the stage no longer has.
- **Previous state comes from the store:** before a run, `data/meta.json` (per-source history) is pulled; for SNOTEL the
  store's last good copy (station files younger than `snotel.max_age_hours`) is seeded like `pipeline restore` does from
  the live site. Before derive, the other sources' small status/index files (`DERIVE_INPUT_PATTERNS`) are pulled so a
  partial run (e.g. only SNOTEL) does not report the rest as missing.
- Sources fail independently; the run exits 1 only if every source failed or the publish failed.
- Default sources (`--all`): obs (alerts, afd, avalanche, hazards, snotel, asos), points (NBM), nohrsc, ecmwf, gefs
  (ecmwf/gefs are no-ops unless enabled in config). Opt-in: `ndfd` (archive/verification only), `maps:<model>`.
- Verification (`models/verify/`) is computed from the forecast archive, not fetched; it stays on `verify.yml` for now.

## Commands

```
python -m ingester list
python -m ingester run snotel asos                 # -> ./output/stage, published to ./output/store (local); -o DIR changes the folder
python -m ingester run --all --prune
python -m ingester run obs --store r2 --dry-run    # reads the R2 manifest, uploads nothing
python -m ingester run obs --store r2              # needs R2_ACCOUNT_ID (or R2_ENDPOINT), R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
python -m ingester publish --store r2 --scope data/points
```

Docker (see `ingester/README.md`): `docker compose -f ingester/compose.yaml run --rm ingester` runs `ingest run --all` into `output/` in the folder you launch from; it uploads to R2 unless `R2_PUSH=0`
to R2 with Docker secrets from `ingester/secrets/`.

## Known limits / next steps

- One manifest per layout: two jobs publishing at the same moment can each write a manifest missing the other's newest
  hashes. Effect: an extra (identical) upload on the next run, never a lost object. A per-source manifest fixes it if
  jobs ever run in parallel against R2.
- CI still deploys through the GitHub workflows (owner-only edits to `.github/`): switching a workflow to
  `ingest run ... --store r2` is an owner step, with the R2 token as an Actions secret.
- CORS / custom `data.` domain / cache headers per path: see `docs/specs/hosting-seo.md` (W1).
- The API and front end reading from the store: not started.

## History plan, step 1 (done)

- Content hashes ignore the time-only fields (`publish.TIME_KEYS`). A file whose content is unchanged is not uploaded, and the manifest keeps the hash of what is stored.
- `v1/_runs/<stamp>.json`: one record per publish (every run, including empty ones), with per-source status and counts.
- `v1/_changes/<stamp>.json`: one record per publish that changed content, with old and new content hashes. Labels: `baseline` (no earlier content hash), `new`, `changed`. It doesn't yet say by how much a value changed; that comes with the field summaries in step 2.
- Still no D1 index. The run and change logs are plain JSON in R2 and can be loaded into D1 later, when the API needs queries across history.
- Next (step 2): forecast issue history per area with the 30-day retention, and per-change field summaries.
