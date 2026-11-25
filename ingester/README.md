# Ingester

The ingester fetches weather and snow data from public sources, organizes it as JSON (and model-map PNGs), and stores
it either in a local folder or in a Cloudflare R2 bucket.

```
ingester/
  pyproject.toml        package metadata and dependencies (pip install -e ingester)
  src/ingester/         the Python package: CLI (__main__.py), sources, stores, publish, runner
  tests/                offline tests (pytest); fakes.py is a copy of the pipeline's fake HTTP session
  Dockerfile, compose*.yaml, entrypoint.sh, secrets/   Docker files
  README.md
```

Spec and design notes: `docs/specs/ingest-r2.md`.

---

## Launching it

### With Docker (recommended)

Run every command from the repository root. The image needs the whole repository as its build context.

**1. Build the image** (once, and again after code changes):

```sh
docker build -f ingester/Dockerfile -t snow-wx-ingester .
```

or, with Compose:

```sh
docker compose -f ingester/compose.yaml build pipeline
```

**2. Run it locally, with no credentials** (writes to `test-output/` on your machine):

```sh
docker compose -f ingester/compose.yaml run --rm pipeline ingest list
docker compose -f ingester/compose.yaml run --rm pipeline ingest run asos --stage /output/stage --dry-run
docker compose -f ingester/compose.yaml run --rm pipeline ingest run asos --stage /output/stage
```

Inside the container the command word is `ingest` (it runs `python -m ingester`). The first run writes:
- `test-output/stage/`: the fetched files, before publishing
- `test-output/store/`: the local store, with exactly the layout R2 would hold

**3. Push to R2** (needs credentials, see below). Dry run first, which reads the bucket's manifest and uploads nothing:

```sh
docker compose -f ingester/compose.yaml -f ingester/compose.r2.yaml run --rm pipeline ingest run asos --stage /output/stage --dry-run
```

Then the real push, the same command without `--dry-run`:

```sh
docker compose -f ingester/compose.yaml -f ingester/compose.r2.yaml run --rm pipeline ingest run asos --stage /output/stage
```

`compose.r2.yaml` sets `R2_PUSH=1`, which makes the container publish to R2 instead of the local store. Without that
file, nothing reaches R2.

The commands above run as your own user, so no `sudo` is needed. The compose file sets `LOCAL_UID`/`LOCAL_GID` to 1000 by default; export your own IDs if yours differ, so the output and secret files stay readable by you:

```sh
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
```

### Without Docker

Create the conda environment from `environment.yml` (once), then from the repository root:

```sh
conda activate snow-wx
pip install -e ingester          # once: installs the package from ingester/src
python -m ingester list
python -m ingester run asos --dry-run
python -m ingester run asos
```

Without the install, point Python at the source folder instead: `PYTHONPATH=ingester/src python -m ingester list`.
On Windows, call the environment's Python directly, as in `CLAUDE.md`, and install with
`C:/miniforge3/envs/snow-wx/python.exe -m pip install -e ingester`.

Tests (offline, from the repository root): `python -m pytest ingester/tests`.

---

## Commands and options

```
python -m ingester list
python -m ingester run [SOURCE ...] [--all] [options]
python -m ingester publish [--scope PATH ...] [options]
```

In the container, use `ingest` in place of `python -m ingester`.

### `list`

Prints every source, whether it runs by default, and the stage paths it writes.

### `run`: fetch sources, derive, publish

| Option | What it does |
|---|---|
| `SOURCE ...` | one or more source names or groups, see [Sources](#sources) |
| `--all` | every default source (all observation and product sources, not `ndfd` or the model maps) |
| `--cycle YYYYMMDDHH` | model cycle for `points`, `ecmwf`, `gefs` and the maps (default: the newest complete cycle) |
| `--force` | run `ecmwf` or `gefs` even when they are disabled in config (local tests) |
| `--workers N` | worker processes for `points` and the maps |
| `--no-derive` | skip the derived files (`meta.json`, search index, catalogs) |

### `publish`: upload an existing stage without fetching

| Option | What it does |
|---|---|
| `--scope PATH ...` | stage paths to publish, e.g. `data/points` (default: all of `data/` and `models/`) |

### Options for both `run` and `publish`

| Option | What it does |
|---|---|
| `--store {local,r2,none}` | where to publish. Default `local`, or the `INGEST_STORE` variable. `none` only fetches into the stage |
| `--stage PATH` | the working folder (default: `ingest.stage_dir`, `data_out/stage`) |
| `--local-root PATH` | the local store folder (default: `ingest.local_store_dir`, `data_out/store`) |
| `--bucket NAME` | the R2 bucket (default: `R2_BUCKET`) |
| `--dry-run` | plan the publish only: nothing is uploaded or deleted. For R2 it still reads the bucket's manifest |
| `--prune` | delete stored objects inside this run's paths that the stage no longer has. Off by default |
| `--archive` / `--no-archive` | also copy each changed object to `archive/runs/<stamp>/`. Default from `ingest.archive` (off) |
| `--config PATH` | another `settings.yml` |
| `-v`, `--verbose` | debug logging |

Exit status: `0` when at least one source succeeded (or nothing ran), `1` when every source failed or the publish
failed, and `2` for a usage error or missing R2 credentials.

---

## Sources

Sources run independently: one failing source does not stop the others. The name is what you pass to `run`.

| Name | Group | Default | Fetches | Upstream |
|---|---|---|---|---|
| `alerts` | obs | yes | active NWS alerts, with the texts for winter alerts | api.weather.gov |
| `afd` | obs | yes | NWS area forecast discussions (AFD) | api.weather.gov, forecast.weather.gov |
| `avalanche` | obs | yes | avalanche danger ratings, unaltered, and zones | api.avalanche.org (avalanche.org public API) |
| `hazards` | obs | yes | NWS watches, warnings and advisories (winter products) | mapservices.weather.noaa.gov |
| `snotel` | obs | yes | SNOTEL snow and weather stations (slow: 3–8 min) | NRCS AWDB, wcc.sc.egov.usda.gov |
| `asos` | obs | yes | airport weather stations | Iowa Environmental Mesonet, mesonet.agron.iastate.edu |
| `points` | product | yes | NBM point forecasts for ski areas, Sno-Parks and SNOTEL sites | NOAA National Blend of Models on AWS (noaa-nbm-grib2-pds); api.weather.gov for grid lookups |
| `nohrsc` | product | yes | NOHRSC snowfall analysis and SNODAS overlay layers | NOAA NOHRSC; SNODAS via NSIDC |
| `ndfd` | product | no | NWS NDFD point forecasts (archive and verification only, not shown on the site) | NOAA NDFD on AWS (noaa-ndfd-pds) |
| `ecmwf` | product | yes | ECMWF HRES, ensemble and AIFS at ski-area summits (needs `ecmwf.enabled`) | ECMWF open data (CC-BY-4.0), data.ecmwf.int and its AWS mirror |
| `gefs` | product | yes | NOAA GEFS ensemble plume at summits (needs `gefs.enabled`) | NOAA GEFS on AWS (noaa-gefs-pds) |
| `maps:hrrr` | maps | no | HRRR model-map PNG frames (slow; needs ecCodes and cartopy) | NOAA model data on AWS, read with Herbie |
| `maps:rrfs` | maps | no | RRFS model-map PNG frames (same needs) | NOAA model data on AWS, read with Herbie |
| `maps:gfs` | maps | no | GFS model-map PNG frames (same needs) | NOAA model data on AWS, read with Herbie |

Groups you can pass in place of names: `obs` (the six observation sources), `products` (`points`, `nohrsc`, `ecmwf`,
`gefs`, `ndfd`) and `maps`.

Licensing: NOAA/NWS, NRCS and Iowa Environmental Mesonet data are open. ECMWF data requires attribution (CC-BY-4.0),
which the JSON files carry. Avalanche ratings are stored unaltered. Do not add a source without checking its terms
(`CLAUDE.md`, PLAN §10).

---

## Where the data goes

### Local store

The default destination, with the layout described below. Host folder: `test-output/store/` in Docker, or
`data_out/store/` without it.

### Cloudflare R2

Pushed only with `--store r2` (or `R2_PUSH=1` in the container). The bucket is set by `R2_BUCKET`.

| Object key | Content |
|---|---|
| `v1/data/...` | the site's data documents: `snotel.geojson`, `points/<area>.json`, `alerts/`, `afd/`, `meta.json`, and so on |
| `v1/models/...` | model products: ECMWF and GEFS JSON, model-map PNG frames |
| `v1/_manifest.json` | sha256 and size of every object, and the last run status of each source (`no-store` cache) |
| `archive/runs/<stamp>/...` | copies of changed objects, only with `--archive` |

Only objects whose content changed are uploaded (sha256 comparison). Cache headers: JSON 60 s, images 1 h, archive
copies immutable. Public access (a custom domain, CORS) is set up separately with the website's hosting work (W1).

The layout is the same locally and in R2, so the local store is a faithful preview of what R2 will hold.

Settings: `config/settings.yml` section `ingest:` (`stage_dir`, `local_store_dir`, `layout`, `archive`).

---

## Credentials (R2)

Credentials are never in code or config. The ingester reads them from Docker secret files or from environment variables.

Create the four files in `ingester/secrets/` (the steps are in `ingester/secrets/README.md`):

```
ingester/secrets/r2_account_id.txt
ingester/secrets/r2_access_key_id.txt
ingester/secrets/r2_secret_access_key.txt
ingester/secrets/r2_bucket.txt
```

They are git-ignored and excluded from the image. Use a token scoped to the one bucket.

Without Docker, set `R2_ACCOUNT_ID` (or `R2_ENDPOINT`), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET`, or
the matching `*_FILE` variables that point at files.

On Fedora with SELinux enforcing, the container may not be able to read the secret files even though their permissions
are correct (it shows "Permission denied" for files you can see). Fix the label only:

```sh
sudo chcon -t container_file_t ingester/secrets/r2_account_id.txt ingester/secrets/r2_access_key_id.txt ingester/secrets/r2_secret_access_key.txt ingester/secrets/r2_bucket.txt
```

If the message is `missing R2 configuration: ...`, the ingester could not read one of the values. It names the missing
keys; the file it failed to read is not named, so check the file's permissions and label first.

---

## Troubleshooting

- **`missing R2 configuration`**: a secret file is empty, unreadable, or not mounted. This shows the container user and
  the size of each secret without printing any values:
  ```sh
  docker compose -f ingester/compose.yaml -f ingester/compose.r2.yaml run --rm --entrypoint /bin/sh pipeline -c 'id; wc -c /run/secrets/r2_*'
  ```
  Sizes of 0 mean an empty file. "Permission denied" means the SELinux label (see Credentials).
- **Files in `test-output/` are owned by root**: left over from runs made with `sudo` in the past. Fix once with
  `sudo chown -R "$(id -u):$(id -g)" test-output`.
- **A source shows `ok: false`**: its error is in the `sources` block of the JSON output and in `data/meta.json`.
  Other sources still publish.
- **`snotel` is slow**: that's normal (3–8 minutes). Run it alone when you're testing.
