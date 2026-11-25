"""Where ingested objects go: a local folder (default) or Cloudflare R2 (S3 API).

Both stores use the same keys, so a local store is an exact, browsable copy of what R2 would hold:

    <root>/v1/data/...            the documents the site reads today (same names, same bytes)
    <root>/v1/models/...          model products (ECMWF/GEFS JSON, model-map PNG frames)
    <root>/v1/_manifest.json      {key: {sha256, size}} for every live object + per-source run status
    <root>/archive/runs/<stamp>/  copies of the objects that changed in that run (optional)

Credentials for R2 come only from the environment (R2_* variables or *_FILE / Docker secret files), read at run time.
"""

from __future__ import annotations

import os
from pathlib import Path


class Store:
    """Minimal object-store interface. Keys are '/'-separated, never start with '/'."""

    kind = "abstract"

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def put(self, key: str, body: bytes, content_type: str, cache_control: str = "", sha256: str = "") -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


def _check_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in key.split("/")):
        raise ValueError(f"bad object key {key!r}")
    return key


class LocalStore(Store):
    """Objects as files under `root` (key = relative path). Content type / cache headers are not kept (R2 only)."""

    kind = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _check_key(key)

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, body: bytes, content_type: str, cache_control: str = "", sha256: str = "") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, p)                      # readers never see a half-written file

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def describe(self) -> str:
        return f"local folder {self.root}"


class R2Store(Store):
    """Cloudflare R2 through its S3-compatible API. `client` is a boto3 S3 client (or a test fake with the same methods)."""

    kind = "r2"

    def __init__(self, client, bucket: str):
        if not bucket:
            raise ValueError("missing R2 bucket")
        self.client, self.bucket = client, bucket

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=_check_key(key))["Body"].read()
        except Exception as exc:  # noqa: BLE001 - botocore raises ClientError; only "not found" means None
            code = str((getattr(exc, "response", None) or {}).get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def put(self, key: str, body: bytes, content_type: str, cache_control: str = "", sha256: str = "") -> None:
        kw = {"Bucket": self.bucket, "Key": _check_key(key), "Body": body, "ContentType": content_type}
        if cache_control:
            kw["CacheControl"] = cache_control
        if sha256:
            kw["Metadata"] = {"sha256": sha256}
        self.client.put_object(**kw)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_check_key(key))

    def describe(self) -> str:
        return f"R2 bucket {self.bucket}"


# ---------- credentials (environment or Docker secrets; never config files) ----------

def secret(name: str) -> str:
    """NAME_FILE (a path), then /run/secrets/<name> (Docker), then the NAME environment variable."""
    file_value = os.environ.get(name + "_FILE", "").strip()
    for candidate in (file_value, f"/run/secrets/{name.lower()}", f"/run/secrets/{name}"):
        if candidate:
            try:
                value = Path(candidate).read_text(encoding="utf-8").strip()
                if value:
                    return value
            except (OSError, UnicodeDecodeError):
                pass
    return os.environ.get(name, "").strip()


def r2_credentials() -> dict:
    account = secret("R2_ACCOUNT_ID")
    endpoint = secret("R2_ENDPOINT") or (f"https://{account}.r2.cloudflarestorage.com" if account else "")
    values = {"access_key": secret("R2_ACCESS_KEY_ID"), "secret_key": secret("R2_SECRET_ACCESS_KEY"),
              "bucket": secret("R2_BUCKET"), "endpoint": endpoint}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise RuntimeError("missing R2 configuration: " + ", ".join(missing)
                           + " (set R2_ACCOUNT_ID or R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET)")
    return values


def open_r2(bucket: str = "") -> R2Store:
    creds = r2_credentials()
    import boto3
    from botocore.config import Config
    client = boto3.client("s3", endpoint_url=creds["endpoint"], aws_access_key_id=creds["access_key"],
                          aws_secret_access_key=creds["secret_key"], region_name="auto",
                          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"}))
    return R2Store(client, bucket or creds["bucket"])
