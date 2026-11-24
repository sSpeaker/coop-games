# Co-op Games

Self-hosted catalog of co-op games for PC, PS4, PS5, Switch and Switch 2.

- Data sources: OpenCritic (co-op tag, score, genres, covers, trailers), Co-optimus (online / couch / LAN player counts per platform), pegi.info (age rating), Steam (genre fallback).
- Storage: SQLite in `/data/coop.db`.
- "Played" marks are stored in the same database and shared by everyone who opens the site.

## Run on CasaOS

The image is built by GitHub Actions on every push to `main` and published as `ghcr.io/sspeaker/coop-games` (`linux/amd64` and `linux/arm64`; tags `latest` and `sha-<commit>`). Only `docker-compose.yml` is needed on the host:

```sh
ssh root@casaos 'mkdir -p /var/lib/casaos/apps/coop-games'
scp docker-compose.yml root@casaos:/var/lib/casaos/apps/coop-games/
ssh root@casaos 'cd /var/lib/casaos/apps/coop-games && docker compose up -d'
```

The app shows up on the CasaOS dashboard (the `x-casaos` block in `docker-compose.yml`). Open `http://<casaos-ip>:8095`.

Data lives in `/DATA/AppData/coop-games` on the host. Change the port or path in `docker-compose.yml`.

### Updating the app

Push to `main`, wait for the "Docker image" workflow, then on the host:

```sh
cd /var/lib/casaos/apps/coop-games && docker compose pull && docker compose up -d
```

The database in `/DATA/AppData/coop-games` is kept. To roll back, pin `image:` to a `sha-<commit>` tag.

To build locally instead: `docker build -t ghcr.io/sspeaker/coop-games:latest .`

## First start

On first start the database is filled from `app/seed/games.csv` (2,820 games exported from the curated Co-op sheet: score, PEGI, genres, platforms, release date). The site is usable immediately.

Then the first update runs automatically and adds covers, banners, trailers, descriptions and Co-optimus player counts, plus any new games. PEGI is searched only for games that are new or have no rating (games without a rating are retried after 30 days). Progress is on the **Data** page (top right).

Rough cost of each step:

| Step | Requests | Time at default delays |
|---|---|---|
| OpenCritic co-op lists | ~115 pages | ~1 min |
| OpenCritic full catalog (to match Co-optimus titles) | ~2,000 pages | ~20 min |
| Co-optimus lists | ~600 pages | ~6 min |
| OpenCritic game pages (cover, banner, trailers, description) | one per game | ~30–40 min |
| PEGI search | 1–2 per new game | seconds to minutes; 60 s pause on HTTP 429 |

If the container restarts mid-update, the job resumes on the next start.

## Updating

- Automatic: every `UPDATE_INTERVAL_HOURS` (default 168 = weekly).
- Manual: **Data → Update now**. A quick update does the following:
  - re-reads the co-op lists and Co-optimus;
  - crawls only new OpenCritic catalog pages;
  - fetches pages of new games and of games released in the last 120 days (scores change);
  - looks up missing PEGI ratings (unrated games are retried every 30 days).
- **Full refresh** re-crawls the whole catalog and every game page.
- API: `POST /api/update`, `POST /api/update?full=true`, `POST /api/update/stop`.

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `UPDATE_INTERVAL_HOURS` | `168` | Auto-update interval; `0` disables |
| `UPDATE_ON_EMPTY_START` | `1` | Run the first update right after the first start |
| `DELAY_OPENCRITIC` / `DELAY_COOPTIMUS` / `DELAY_PEGI` / `DELAY_STEAM` | `0.6` / `0.6` / `1.0` / `1.0` | Seconds between requests per site |
| `BACKOFF_429` | `60` | Pause after HTTP 429 |
| `IMPERSONATE` | `chrome` | Browser TLS fingerprint used by curl_cffi; empty = plain httpx |
| `REFRESH_RECENT_DAYS` / `REFRESH_EVERY_DAYS` | `120` / `7` | Which game pages a quick update re-fetches |
| `CATALOG_STOP_AFTER` | `3` | Incremental catalog crawl stops after this many pages with no new games |

## Co-optimus blocked (HTTP 403 from Cloudflare)

The crawler uses curl_cffi with a Chrome fingerprint, loads games.php first for cookies and sends the same headers as the site's own XHR. If Cloudflare still answers 403:

- The rest of the update still runs, and the previous Co-optimus data is kept. The Data page shows `partial: crawl_cooptimus: …`.
- Fallback: **Data → Import Co-optimus data from your browser**.
  1. Copy the script.
  2. Run it in the browser console on co-optimus.com/games.php (about 10 min).
  3. Upload the downloaded `coopt.json`.

  The import rematches titles and rebuilds the game list without any network requests. New games found this way get covers and PEGI on the next update.

## Manual fixes

Overrides win over scraped data. Run the following, then trigger an update (the genre index is rebuilt at the end of each update):

```sh
docker exec -it coop-games python - <<'PY'
import sqlite3
c = sqlite3.connect('/data/coop.db')
# Fix genres of a game (OpenCritic id from its URL)
c.execute("INSERT OR REPLACE INTO overrides(game_id, field, value) VALUES(18192, 'genres', 'Action, Adventure')")
# Fix a wrong PEGI rating directly; the updater does not overwrite a found rating
c.execute("UPDATE games SET pegi=16, pegi_title='manual' WHERE id=18192")
c.commit()
PY
```

## Matching rules

- **Co-optimus → OpenCritic:** match by normalized title (case, accents and punctuation ignored); if that fails, compare titles with edition words removed. Matches whose release years differ by more than one year are rejected (prevents e.g. Doom 1993 ↔ Doom 2016).
- **PEGI:** only exact or edition-stripped title matches are accepted; near matches like "Black Ops" → "Black Ops 6" are ignored, leaving the rating empty.
- **Genres:** taken in this order: OpenCritic game page → OpenCritic list → Co-optimus genre label → Steam → `Other`.

## Tests

```sh
pip install -r requirements.txt pytest
pytest -q tests
```
