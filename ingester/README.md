# Ingester

The ingester fetches weather and snow data from public sources and stores it, as JSON (and model-map PNGs), either in a
local folder or in a Cloudflare R2 bucket. It is a standalone app: it builds no website files, and nothing outside this
folder is needed to run it.

```
ingester/
  pyproject.toml        package metadata and dependencies (pip install -e ingester)
  environment.yml       conda environment (GRIB, cartopy and the other compiled packages)
  src/ingester/         the package: CLI (__main__.py), run (runner.py), sources registry, stores, publish
    fetch/              the data-source code, one module per source (copied from the website's pipeline, see below)
    obs.py              runs the observation sources (alerts, afd, avalanche, hazards, snotel, asos)
    ecmwf_run.py        ECMWF run with its attempt log
  config/               settings.yml (the ingest section and each source's settings), models.yml, summary_rules.yml
  data/                 point lists the forecast sources need: ski_areas.json, rec_points.json, snotel_points.json
  tests/                offline tests (pytest)
  Dockerfile, .dockerignore, compose.yaml, entrypoint.sh, secrets/   Docker files
  README.md
```

Spec and design notes: `docs/specs/ingest-r2.md`.

---

## Launching it

### With Docker (recommended)

Every command below is run from the folder you want the output in. The output goes to `output/` in that folder, and
`output/` and `data_cache/` are created there if they are missing. Replace `/path/to/snow-wx` with where the repository is.

#### One-time setup

1. **Build the image** (again after code changes). The build context is the `ingester/` folder, and the image contains
   only the ingester:

   ```sh
   docker compose -f /path/to/snow-wx/ingester/compose.yaml build ingester
   ```

2. **Create the R2 secret files** in `ingester/secrets/`, as described in `ingester/secrets/README.md`. They are required
   for every run, including runs that don't push to R2.

3. **Your user ID** (optional). The container gives `output/` and `data_cache/` to user 1000 by default. If your UID
   and GID differ, export them before running:

   ```sh
   export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
   ```

#### Run without pushing to R2 (local store only)

Set `R2_PUSH=0`. Nothing is uploaded, and the results are written to `output/store/` on your machine.

```sh
cd ~/ingest-run
R2_PUSH=0 docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run asos --dry-run
R2_PUSH=0 docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run asos
```

The first command shows what would be stored, without fetching or writing data. The second fetches `asos` and writes it
to `output/stage/` and `output/store/`.

#### Run and push to R2

`R2_PUSH` defaults to `1`, so the command below uploads changed files to the bucket. Run the dry run first: it reads the
bucket's manifest and uploads nothing.

```sh
cd ~/ingest-run
docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run asos --dry-run   # R2: reads the manifest, uploads nothing
docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run asos             # R2: uploads changed files
```

The R2 bucket is set by the `r2_bucket` secret. The stage and local store are still written to `output/` on your machine.

#### Other commands

```sh
docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest list                # list sources; never uploads
docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run --all           # every default source (pushes to R2 unless R2_PUSH=0)
docker compose -f /path/to/snow-wx/ingester/compose.yaml run --rm ingester ingest run asos -o other   # another output folder (see below)
```

Inside the container the command word is `ingest` (it runs `python -m ingester`).

The container starts as root for a moment, only to give `output/` and `data_cache/` to your user, and then runs the
ingester as that user.

- `output/stage/`: the fetched files, before publishing
- `output/store/`: the local store, with exactly the layout R2 would hold

`-o DIR` (or `--output DIR`, or `--o DIR`) picks another output folder, relative to the folder you run from. Compose mounts
only `output/` into the container, so with Docker a different folder is written inside the container and is lost when it
stops. To use another folder with Docker, add a mount for it in `ingester/compose.yaml`.

### Without Docker

Create the conda environment from `ingester/environment.yml` (once), then install the package:

```sh
conda env create -f /path/to/snow-wx/ingester/environment.yml
conda activate ingester
pip install -e /path/to/snow-wx/ingester      # once: installs the package from ingester/src
python -m ingester list
python -m ingester run asos --dry-run
python -m ingester run asos
```

Without the install, point Python at the source folder instead: `PYTHONPATH=ingester/src python -m ingester list`.
Run the commands from the folder you want the output in: the output goes to `output/` there (see `-o` below).

Tests (offline): `python -m pytest ingester/tests`.

### Keeping the copied data up to date

The ingester has its own copies of the data-source code (`src/ingester/fetch/`), its settings and its point lists
(`config/`, `data/`). They were copied from the website's `pipeline/`, `config/` and `data/` folders, which still have
their own. When a source changes in the website code, copy the module again (keeping the imports relative) and check the
tests. The point lists are generated by the website side (`python -m pipeline catalog`, `python -m pipeline catalog
--snotel`): copy `data/ski_areas.json`, `data/rec_points.json` and `data/snotel_points.json` over when they change.
Until the website reads its data from the store, these copies are maintained by hand.

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

### `run`: fetch sources, then publish

| Option | What it does |
|---|---|
| `SOURCE ...` | one or more source names or groups, see [Sources](#sources) |
| `--all` | every default source (all observation and product sources, not `ndfd` or the model maps) |
| `--cycle YYYYMMDDHH` | model cycle for `points`, `ecmwf`, `gefs` and the maps (default: the newest complete cycle) |
| `--force` | run `ecmwf` or `gefs` even when they are disabled in config (local tests) |
| `--workers N` | worker processes for `points` and the maps |

### `publish`: upload an existing stage without fetching

| Option | What it does |
|---|---|
| `--scope PATH ...` | stage paths to publish, e.g. `data/points` (default: all of `data/` and `models/`) |

### Options for both `run` and `publish`

| Option | What it does |
|---|---|
| `--store {local,r2,none}` | where to publish. Default `local`, or the `INGEST_STORE` variable. `none` only fetches into the stage |
| `-o DIR`, `--output DIR` | the output folder, relative to the folder you launch from (default: `ingest.output_dir`, i.e. `output/`). It holds `stage/` (working files) and `store/` (the local store). `--o` works as a short form |
| `--local-root PATH` | the local store folder (default: `<output>/store`) |
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

The default destination, with the layout described below: `output/store/` in the folder you launch from.

### Cloudflare R2

Pushed with `--store r2` (or `R2_PUSH=1`, the container default). Test runs set `R2_PUSH=0`. The bucket is set by `R2_BUCKET`.

| Object key | Content |
|---|---|
| `v1/data/...` | the site's data documents: `snotel.geojson`, `points/<area>.json`, `alerts/`, `afd/`, `meta.json`, and so on |
| `v1/models/...` | model products: ECMWF and GEFS JSON, model-map PNG frames |
| `v1/_manifest.json` | sha256 and size of every object, and the last run status of each source (`no-store` cache) |
| `v1/_runs/<stamp>.json` | one record per publish: each source's status, and counts of new, changed, unchanged and deleted objects |
| `v1/_changes/<stamp>.json` | one record per publish that changed content. Each object is `baseline` (no earlier content hash: a first publish, or a manifest from before content hashes), `new`, or `changed`, with old and new content hashes |
| `archive/runs/<stamp>/...` | copies of changed objects, only with `--archive` |

Only objects whose content changed are uploaded. Content is compared without the time-only fields (`generated_at`, `checked_at`, `fetched_at`, `age_h`), so a run that only refreshes timestamps uploads nothing; its run record still says so. Cache headers: JSON 60 s, images 1 h, archive
copies immutable. Public access (a custom domain, CORS) is set up separately with the website's hosting work (W1).

The layout is the same locally and in R2, so the local store is a faithful preview of what R2 will hold.

### How change detection and logs work

Every publish compares each file with what is stored, then records what happened.

- **Content hash.** For JSON files, the hash is taken over the document with the time-only fields removed (`generated_at`,
  `checked_at`, `fetched_at`, `age_h`), with keys sorted. Other files are hashed as bytes. The manifest stores this hash for
  each object.
- **Upload only on change.** If an object's content hash matches the stored one, it is skipped and its stored copy is left
  alone. The manifest keeps describing what is stored, so a skipped file still shows its old timestamp.
- **Run record** (`v1/_runs/<stamp>.json`). Written on every publish, including runs with no changes. It holds each source's
  status and the counts: `baseline`, `new`, `changed`, `unchanged`, `deleted`.
- **Change record** (`v1/_changes/<stamp>.json`). Written only when content changed. It lists each object with its
  label and its old and new content hashes. The labels are `baseline` (no earlier content hash, from a first publish or a
  manifest written before hashes), `new` (the key didn't exist), and `changed` (the hash differs). Deleted objects are
  listed as `deleted`.
- **Order.** Data files are uploaded first, then the run and change records, and the manifest last.

The change record says which objects changed, not by how much. Field-level summaries come later with the forecast history.

Settings: `config/settings.yml` section `ingest:` (`output_dir`, `layout`, `archive`).

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
  docker compose -f ingester/compose.yaml run --rm --entrypoint /bin/sh ingester -c 'id; wc -c /run/secrets/r2_*'
  ```
  Sizes of 0 mean an empty file. "Permission denied" means the SELinux label (see Credentials).
- **A source shows `ok: false`**: its error is in the `sources` block of the JSON output and in `data/meta.json`.
  Other sources still publish.
- **`snotel` is slow**: that's normal (3–8 minutes). Run it alone when you're testing.
