# R2 credentials for Docker secrets

Put one value in each file, no quotes and no extra lines. These files are git-ignored; never commit them.

| File | What goes in it |
|---|---|
| `r2_account_id.txt` | your Cloudflare account ID |
| `r2_access_key_id.txt` | the access key ID of a scoped R2 API token |
| `r2_secret_access_key.txt` | the secret access key of that token |
| `r2_bucket.txt` | the bucket name |

Create them without putting the values in your shell history, then make them private to you (run from the repo root):

```sh
cd ingester/secrets
printf '%s' 'YOUR_ACCOUNT_ID'        > r2_account_id.txt
printf '%s' 'YOUR_ACCESS_KEY_ID'     > r2_access_key_id.txt
printf '%s' 'YOUR_SECRET_ACCESS_KEY' > r2_secret_access_key.txt
printf '%s' 'YOUR_BUCKET_NAME'       > r2_bucket.txt
chmod 600 r2_*.txt
cd ../..
```

Compose mounts them into the container at `/run/secrets/<name>`. The container reads them at run time (`ingester/src/ingester/store.py`).
They are never copied into the image: `.dockerignore` excludes this folder, and the Dockerfile copies only the Python files.

On Fedora (SELinux enforcing), the mounted files also need the container label. If the container can't read them, run
`sudo chcon -t container_file_t ingester/secrets/r2_*.txt` (only the label changes; see `ingester/README.md`).
