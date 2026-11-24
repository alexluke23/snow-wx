# W1 cutover checklist (rehearsed Nov 19 2026, dev18; awaiting the real domain)

Rehearsal evidence: `python tools/w1_rehearsal.py --origin https://snowwx.example --base ""` (and `--base /app`): 15 of 15 checks pass offline (tests/test_stub.py runs both). It builds the site for a placeholder domain with the W2 pages and W4 PWA forced on and checks that
**nothing hard-codes `github.io`** (grep over every built html/js/json/xml/txt file; links to the code repository are allowed), sitemap / robots / canonical / `og:url` / JSON-LD / manifest / service-worker base / `pwa-config.js` / the 404 `<base>` / the `#id` redirect map all follow `site.origin` + `site.base_path`,
no page has an inline `<script>`, no internal link is broken, and the GitHub Pages redirect stub (`python -m pipeline stub`) covers every page the live site serves and every ski-area `#id`.
Found and fixed by the rehearsal: `pages.py` and `pwa.py` injected inline scripts (`id-redirect`, `SNOWWX_PWA`), which a strict CSP would block; both are files now (`js/id-redirect.js`, `js/pwa-config.js`).
Still hard-coded in the repo (all intended): `config/settings.yml` `site.origin` (the one place), links to `github.com/alexluke23/snow-wx` (code/issue/release pages), `docs/` text.

## A. Owner decisions and accounts (blocks everything below)
- [ ] Domain set by owner at W1; DNS under Cloudflare. Cloudflare Pages project (direct upload or Git), R2 bucket + API token if data moves (spec `hosting-seo.md`, "R2 sync").
- [ ] Legal drafts reviewed (`web/disclaimer.html`, `privacy.html`, `terms.html`: DRAFT/noindex) and the analytics provider chosen (`docs/specs/launch-readiness.md`).

## B. One config PR (I can prepare it once the domain exists)
- [ ] `config/settings.yml`: `site.origin: https://<domain>`, `site.base_path: ""` (it is `"/snow-wx"` today), `site.data_origin` if R2, `pages.enabled: true`. **`pwa.enabled` stays false until the domain is live and checked on real phones**, then true (kill switch: `pwa.kill: true`).
- [ ] Repo variable `SITE_ORIGIN` (workflows) = the new origin. `pipeline restore` (previous good SNOTEL copy) and the monitor read it; keep the old origin there until the new site serves the newest deploy.
- [ ] Re-run `python tools/w1_rehearsal.py --origin https://<domain> --base ""`: must be 15/15.

## C. Workflow edits (OWNER: dev sessions never edit `.github/`; text to paste)
- [ ] `update-site.yml` after the model/points tars are unpacked and `build` has run: `python -m pipeline pages --out build` then (when enabling the PWA) `python -m pipeline pwa --out build`; fail the job if the file count exceeds 20,000 (the size guard already exists).
- [ ] Deploy `build/` to Cloudflare Pages (wrangler or the official action; token as a secret). Keep the GitHub Pages deploy running until two weeks after cutover (rollback).
- [ ] Copy `docs/cloudflare_headers.draft` to `build/_headers`. Ship the CSP as **`Content-Security-Policy-Report-Only` for a week**, then enforce. `python tools/browser_check.py --only csp` must pass first (it does today).
- [ ] Redirect stub: `python -m pipeline stub --origin https://<domain> --out stub` and deploy that folder to GitHub Pages in place of the old site once the new one is verified (a separate small workflow or branch; stub pages are `noindex` with a canonical to the new address).

## D. Verify on the new origin (commands)
- [ ] `python tools/browser_check.py --build build` against a local copy, then the same checks against the live URL (parity check spec in `hosting-seo.md`: 30 sampled URLs, GitHub Pages vs new origin).
- [ ] `python -m pipeline linkcheck --build build --outbound --data` (internal links, robots/sitemap/canonical, every outbound link).
- [ ] First build after the cutover: `restore` log shows stations restored (or "no copy" on purpose); the monitor job reads the new `meta.json`; status page loads; `data/meta.json` is the last file written.
- [ ] Lighthouse (median of 3 interleaved runs, mobile): obs map and area page not worse than today (`docs/budgets_baseline.md`).
- [ ] Search Console: submit `sitemap.xml`; confirm the stub's canonical/redirects; remove `noindex` from the legal pages only after sign-off.
- [ ] Update the privacy page host sentence ("served from GitHub Pages (planned: Cloudflare)") and regenerate: `python tools/gen_site_pages.py`; add the analytics provider host if enabled (tests fail until you do).
- [ ] Feedback address (`site.feedback_email`) still reads from config; no address in any page.

## E. Rollback
DNS back to GitHub Pages (TTL 5 min); the Pages deploy kept running makes this a CNAME change. `pwa.kill: true` ships a worker that unregisters itself for installed users. R2 data is additive and can stay.
