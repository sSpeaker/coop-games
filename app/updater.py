"""Database update job: crawls OpenCritic, Co-optimus, pegi.info and Steam, then rebuilds the games table."""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from . import config, db, scrapers
from .text import norm, strip_edition, year_of

log = logging.getLogger("updater")

_job_lock = threading.Lock()
_stop = threading.Event()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_running():
    return _job_lock.locked()


def request_stop():
    _stop.set()


def start_background(full=False):
    """Start an update in a thread; returns False if one is already running."""
    if _job_lock.locked():
        return False
    t = threading.Thread(target=run, kwargs={"full": full}, daemon=True, name="updater")
    t.start()
    return True


def start_import(payload):
    """Import Co-optimus rows exported from a browser, then rematch and rebuild games (no network)."""
    if _job_lock.locked():
        return False
    t = threading.Thread(target=_run_import, args=(payload,), daemon=True, name="coopt-import")
    t.start()
    return True


def _run_import(payload):
    if not _job_lock.acquire(blocking=False):
        return
    conn = db.connect()
    job = Job(conn, None, False)
    try:
        job.status("running", "Starting")
        by_platform = {}
        for x in payload:
            if x.get("platform") in config.PLATFORMS and str(x.get("coopt_id", "")).isdigit() and x.get("title"):
                x["coopt_id"] = int(x["coopt_id"])
                by_platform.setdefault(x["platform"], []).append(x)
        for platform, rows in by_platform.items():
            job.status("running", f"Importing Co-optimus · {platform}")
            job.store_coopt(platform, rows)
        job.match_cooptimus()
        job.build_games()
        job.resolve_genres(steam=False)
        job.finish("ok (Co-optimus import)")
    except Exception as e:  # noqa: BLE001
        log.exception("import failed")
        job.finish("error: %s" % e)
    finally:
        conn.close()
        _job_lock.release()


def run(full=False):
    if not _job_lock.acquire(blocking=False):
        return False
    _stop.clear()
    conn = db.connect()
    fetcher = scrapers.Fetcher(stop_flag=_stop.is_set)
    job = Job(conn, fetcher, full)
    try:
        job.status("running", "Starting")
        errors = []
        # A failing source (e.g. a site blocking the crawler) must not stop the other steps.
        for step in (job.crawl_opencritic, job.crawl_cooptimus, job.match_cooptimus, job.build_games,
                     job.enrich_pages, job.resolve_genres, job.fetch_pegi):
            try:
                step()
            except scrapers.StopRequested:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("step %s failed", step.__name__)
                errors.append(f"{step.__name__}: {e}")
        if job.stats.get("coopt_error"):
            errors.append("crawl_cooptimus: " + job.stats["coopt_error"])
        job.stats["errors"] = errors
        job.finish("ok" if not errors else "partial: " + "; ".join(errors)[:300])
    except scrapers.StopRequested:
        job.finish("stopped")
    except Exception as e:  # noqa: BLE001 - surface any failure in the UI
        log.exception("update failed")
        job.finish("error: %s" % e)
    finally:
        fetcher.close()
        conn.close()
        _job_lock.release()
    return True


class Job:
    def __init__(self, conn, fetcher, full):
        self.conn = conn
        self.f = fetcher
        self.full = full
        self.stats = {}
        self.coopt_ok = True  # False when Co-optimus could not be read; build_games then keeps player counts

    # ------------------------------------------------------------ status

    def status(self, state, step, done=None, total=None):
        with db.write_lock(), self.conn:
            db.set_meta(self.conn, "update_state", state)
            db.set_meta(self.conn, "update_step", step)
            db.set_meta(self.conn, "update_done", done)
            db.set_meta(self.conn, "update_total", total)
            if state == "running" and step == "Starting":
                db.set_meta(self.conn, "update_started_at", now_iso())
        log.info("%s %s/%s", step, done, total)

    def finish(self, result):
        with db.write_lock(), self.conn:
            db.set_meta(self.conn, "update_state", "idle")
            db.set_meta(self.conn, "update_step", None)
            db.set_meta(self.conn, "update_done", None)
            db.set_meta(self.conn, "update_total", None)
            db.set_meta(self.conn, "last_update_at", now_iso())
            db.set_meta(self.conn, "last_update_result", result)
            db.set_meta(self.conn, "last_update_stats", json.dumps(self.stats))
        log.info("update finished: %s %s", result, self.stats)

    # ------------------------------------------------------------ OpenCritic lists

    def _upsert_catalog(self, rows, platform, coop):
        ts = now_iso()
        new = 0
        with db.write_lock(), self.conn:
            for r in rows:
                cur = self.conn.execute(
                    "SELECT 1 FROM catalog_platform WHERE oc_id=? AND platform=?", (r["oc_id"], platform)
                ).fetchone()
                if not cur:
                    new += 1
                self.conn.execute(
                    """INSERT INTO catalog(oc_id, slug, name, norm, score, release_date, genres, image, seen_at)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(oc_id) DO UPDATE SET slug=excluded.slug, name=excluded.name, norm=excluded.norm,
                         score=excluded.score, release_date=COALESCE(excluded.release_date, catalog.release_date),
                         genres=CASE WHEN excluded.genres<>'' THEN excluded.genres ELSE catalog.genres END,
                         image=COALESCE(excluded.image, catalog.image), seen_at=excluded.seen_at""",
                    (r["oc_id"], r["slug"], r["name"], norm(r["name"]), r["score"], r["release_date"],
                     ", ".join(r["genres"]), r["image"], ts),
                )
                if coop:
                    self.conn.execute(
                        """INSERT INTO catalog_platform(oc_id, platform, oc_coop) VALUES(?,?,1)
                           ON CONFLICT(oc_id, platform) DO UPDATE SET oc_coop=1""",
                        (r["oc_id"], platform),
                    )
                else:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO catalog_platform(oc_id, platform, oc_coop) VALUES(?,?,0)",
                        (r["oc_id"], platform),
                    )
        return new

    def crawl_opencritic(self):
        for platform, (slug, _) in config.PLATFORMS.items():
            # Co-op tagged list: always crawled in full so the co-op flag stays exact.
            coop_ids = []
            page = 1
            while True:
                self.status("running", f"OpenCritic co-op list · {platform}", page, None)
                r = self.f.get(scrapers.oc_browse_url(slug, page, True), config.DELAY_OPENCRITIC)
                rows = scrapers.parse_oc_browse(r.text)
                if not rows:
                    break
                self._upsert_catalog(rows, platform, True)
                coop_ids += [x["oc_id"] for x in rows]
                page += 1
            if coop_ids:
                with db.write_lock(), self.conn:
                    marks = ",".join("?" * len(coop_ids))
                    self.conn.execute(
                        f"UPDATE catalog_platform SET oc_coop=0 WHERE platform=? AND oc_id NOT IN ({marks})",
                        (platform, *coop_ids),
                    )
            self.stats[f"oc_coop_{platform}"] = len(coop_ids)

            # Full catalog (needed to match Co-optimus titles): complete crawl once, then only new pages.
            full_key = f"catalog_full_{platform}"
            do_full = self.full or not db.get_meta(self.conn, full_key)
            page, quiet, added = 1, 0, 0
            while True:
                self.status("running", f"OpenCritic catalog · {platform}", page, None)
                r = self.f.get(scrapers.oc_browse_url(slug, page, False), config.DELAY_OPENCRITIC)
                rows = scrapers.parse_oc_browse(r.text)
                if not rows:
                    break
                new = self._upsert_catalog(rows, platform, False)
                added += new
                quiet = 0 if new else quiet + 1
                if not do_full and quiet >= config.CATALOG_STOP_AFTER:
                    break
                page += 1
            if do_full:
                with db.write_lock(), self.conn:
                    db.set_meta(self.conn, full_key, now_iso())
            self.stats[f"oc_catalog_new_{platform}"] = added

    # ------------------------------------------------------------ Co-optimus

    def crawl_cooptimus(self):
        self.f.warm_up(f"{scrapers.COOPT}/games.php", config.DELAY_COOPTIMUS)
        failed = []
        for platform, (_, system) in config.PLATFORMS.items():
            rows, page, last = [], 1, 1
            try:
                while page <= last:
                    self.status("running", f"Co-optimus · {platform}", page, last)
                    r = self.f.get(scrapers.coopt_url(system, page), config.DELAY_COOPTIMUS,
                                   headers=scrapers.COOPT_XHR_HEADERS)
                    got, lp = scrapers.parse_coopt_page(r.text)
                    last = max(last, lp)
                    if not got:
                        break
                    rows += got
                    page += 1
            except scrapers.StopRequested:
                raise
            except Exception as e:  # noqa: BLE001
                # Co-optimus only adds player counts; don't let it block covers, trailers and PEGI.
                # Keep the previous rows for this platform: a partial crawl would drop games.
                code = (getattr(e, "status", None) or getattr(getattr(e, "response", None), "status_code", None)
                        or type(e).__name__)
                url = scrapers.coopt_url(system, page)
                log.warning("Co-optimus unavailable (%s at %s); skipping, previous player counts are kept", code, url)
                self.coopt_ok = False
                failed.append(f"{code} {url}")
                continue
            self.store_coopt(platform, rows)
        if failed:
            self.stats["coopt_error"] = "; ".join(failed)[:300] + " (use Data → Import Co-optimus data)"

    def store_coopt(self, platform, rows):
        if not rows:
            return
        with db.write_lock(), self.conn:
            self.conn.execute("DELETE FROM coopt WHERE platform=?", (platform,))
            for x in rows:
                self.conn.execute(
                    """INSERT OR REPLACE INTO coopt(coopt_id, platform, title, norm, genre, online, couch, lan, features, release)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (x["coopt_id"], platform, x["title"], norm(x["title"]), x.get("genre"), x.get("online") or 0,
                     x.get("couch") or 0, x.get("lan") or 0, json.dumps(x.get("features") or []), x.get("release")),
                )
        self.stats[f"coopt_{platform}"] = len(rows)

    def match_cooptimus(self):
        self.status("running", "Matching Co-optimus to OpenCritic")
        cat = self.conn.execute("SELECT oc_id, norm, name, release_date FROM catalog").fetchall()
        plats = {}
        for r in self.conn.execute("SELECT oc_id, platform FROM catalog_platform"):
            plats.setdefault(r["oc_id"], set()).add(r["platform"])
        by_norm, by_strip = {}, {}
        for c in cat:
            by_norm.setdefault(c["norm"], []).append(c)
            by_strip.setdefault(strip_edition(c["name"]), []).append(c)

        matched = rejected = 0
        updates = []
        for row in self.conn.execute("SELECT coopt_id, platform, title, norm, release FROM coopt").fetchall():
            cands = by_norm.get(row["norm"]) or by_strip.get(strip_edition(row["title"])) or []
            y = year_of(row["release"])
            best, best_key = None, None
            for c in cands:
                cy = year_of(c["release_date"])
                if y and cy and abs(y - cy) > 1:
                    continue
                key = (row["platform"] not in plats.get(c["oc_id"], set()), abs(y - cy) if (y and cy) else 5)
                if best_key is None or key < best_key:
                    best, best_key = c, key
            if cands and not best:
                rejected += 1
            if best:
                matched += 1
            updates.append((best["oc_id"] if best else None, row["coopt_id"], row["platform"]))
        with db.write_lock(), self.conn:
            self.conn.executemany("UPDATE coopt SET oc_id=? WHERE coopt_id=? AND platform=?", updates)
        self.stats["coopt_matched"] = matched
        self.stats["coopt_rejected_by_year"] = rejected

    # ------------------------------------------------------------ games

    def build_games(self):
        self.status("running", "Building game list")
        ids = {r[0] for r in self.conn.execute("SELECT DISTINCT oc_id FROM catalog_platform WHERE oc_coop=1")}
        ids |= {r[0] for r in self.conn.execute(
            "SELECT DISTINCT c.oc_id FROM coopt c JOIN catalog_platform p ON p.oc_id=c.oc_id WHERE c.oc_id IS NOT NULL")}
        ts = now_iso()
        # Without fresh Co-optimus data keep the stored player counts, features and source.
        coopt_set = ("online=excluded.online, couch=excluded.couch, lan=excluded.lan, features=excluded.features,\n"
                     "                         source=excluded.source, ") if self.coopt_ok else ""
        with db.write_lock(), self.conn:
            for gid in ids:
                c = self.conn.execute("SELECT * FROM catalog WHERE oc_id=?", (gid,)).fetchone()
                if not c:
                    continue
                co = self.conn.execute("SELECT * FROM coopt WHERE oc_id=?", (gid,)).fetchall()
                online = max([x["online"] for x in co], default=None)
                couch = max([x["couch"] for x in co], default=None)
                lan = max([x["lan"] for x in co], default=None)
                feats = []
                for x in co:
                    for f in json.loads(x["features"] or "[]"):
                        if f not in feats and f not in ("Online", "Couch"):
                            feats.append(f)
                in_oc = self.conn.execute(
                    "SELECT 1 FROM catalog_platform WHERE oc_id=? AND oc_coop=1", (gid,)).fetchone()
                source = "both" if (in_oc and co) else ("opencritic" if in_oc else "co-optimus")
                self.conn.execute(
                    f"""INSERT INTO games(id, slug, name, norm, score, release_date, genres, image, online, couch, lan,
                                         features, source, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET slug=excluded.slug, name=excluded.name, norm=excluded.norm,
                         score=COALESCE(excluded.score, games.score),
                         release_date=COALESCE(games.release_date, excluded.release_date),
                         genres=CASE WHEN excluded.genres<>'' AND (games.genres IS NULL OR games.genres='')
                                     THEN excluded.genres ELSE games.genres END,
                         image=COALESCE(games.image, excluded.image),
                         {coopt_set}updated_at=excluded.updated_at""",
                    (gid, c["slug"], c["name"], c["norm"], c["score"], c["release_date"], c["genres"] or "",
                     c["image"], online, couch, lan, json.dumps(feats), source, ts),
                )
                self.conn.execute("DELETE FROM game_platform WHERE game_id=?", (gid,))
                self.conn.executemany(
                    "INSERT INTO game_platform(game_id, platform) VALUES(?,?)",
                    [(gid, p[0]) for p in self.conn.execute(
                        "SELECT platform FROM catalog_platform WHERE oc_id=?", (gid,))],
                )
        self.stats["games"] = len(ids)

    def enrich_pages(self):
        today = datetime.now(timezone.utc)
        recent = (today - timedelta(days=config.REFRESH_RECENT_DAYS)).strftime("%Y-%m-%d")
        stale = (today - timedelta(days=config.REFRESH_EVERY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.conn.execute(
            """SELECT id, slug FROM games
               WHERE page_fetched_at IS NULL OR ? = 1
                  OR (release_date >= ? AND page_fetched_at < ?)
               ORDER BY page_fetched_at IS NOT NULL, score DESC""",
            (1 if self.full else 0, recent, stale),
        ).fetchall()
        for i, r in enumerate(rows, 1):
            self.status("running", "OpenCritic game pages", i, len(rows))
            resp = self.f.get(f"{scrapers.OC}/game/{r['id']}/{r['slug']}", config.DELAY_OPENCRITIC, accept_404=True)
            if resp is None:
                with db.write_lock(), self.conn:
                    self.conn.execute("UPDATE games SET page_fetched_at=? WHERE id=?", (now_iso(), r["id"]))
                continue
            d = scrapers.parse_oc_game(resp.text)
            with db.write_lock(), self.conn:
                self.conn.execute(
                    """UPDATE games SET description=COALESCE(?, description),
                         genres=CASE WHEN ?<>'' THEN ? ELSE genres END,
                         score=COALESCE(?, score), release_date=COALESCE(?, release_date),
                         image=COALESCE(?, image), banner=COALESCE(?, banner, ?),
                         trailers=?, page_fetched_at=? WHERE id=?""",
                    (d.get("description"), ", ".join(d["genres"]), ", ".join(d["genres"]), d.get("score"),
                     d.get("release_date"), d.get("image"), d.get("banner"), d.get("box_art"),
                     json.dumps(d["trailers"]), now_iso(), r["id"]),
                )
        self.stats["pages_fetched"] = len(rows)

    def resolve_genres(self, steam=True):
        self.status("running", "Resolving genres")
        missing = self.conn.execute(
            "SELECT id, name, genre_checked_at FROM games WHERE genres IS NULL OR genres=''").fetchall()
        steam_done = 0
        for i, g in enumerate(missing, 1):
            labels = [r["genre"] for r in self.conn.execute("SELECT genre FROM coopt WHERE oc_id=?", (g["id"],))]
            genres = []
            for lab in labels:
                for x in scrapers.coopt_genres(lab):
                    if x not in genres:
                        genres.append(x)
            if not genres and not steam:
                continue
            if not genres and not g["genre_checked_at"]:
                self.status("running", "Steam genre lookup", i, len(missing))
                r = self.f.get(f"{scrapers.STEAM}/api/storesearch/", config.DELAY_STEAM,
                               params={"term": g["name"], "l": "english", "cc": "us"})
                appid = scrapers.parse_steam_search(r.text, g["name"])
                if appid:
                    r2 = self.f.get(f"{scrapers.STEAM}/api/appdetails", config.DELAY_STEAM,
                                    params={"appids": appid, "filters": "genres"})
                    genres = scrapers.parse_steam_genres(r2.text, appid)
                steam_done += 1
            with db.write_lock(), self.conn:
                self.conn.execute("UPDATE games SET genres=?, genre_checked_at=? WHERE id=?",
                                  (", ".join(genres), now_iso(), g["id"]))
        self.stats["steam_lookups"] = steam_done
        self.rebuild_genre_index()

    def rebuild_genre_index(self):
        overrides = {r["game_id"]: r["value"] for r in self.conn.execute(
            "SELECT game_id, value FROM overrides WHERE field='genres'")}
        with db.write_lock(), self.conn:
            self.conn.execute("DELETE FROM game_genre")
            for g in self.conn.execute("SELECT id, genres FROM games").fetchall():
                raw = overrides.get(g["id"], g["genres"]) or ""
                genres = [x.strip() for x in raw.split(",") if x.strip()] or ["Other"]
                self.conn.executemany("INSERT OR IGNORE INTO game_genre(game_id, genre) VALUES(?,?)",
                                      [(g["id"], x) for x in genres])

    def fetch_pegi(self):
        retry_before = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self.conn.execute(
            """SELECT id, name FROM games
               WHERE pegi_checked_at IS NULL OR (pegi IS NULL AND pegi_checked_at < ?)
               ORDER BY pegi_checked_at IS NOT NULL, score DESC""",
            (retry_before,),
        ).fetchall()
        found = 0
        for i, g in enumerate(rows, 1):
            self.status("running", "PEGI ratings", i, len(rows))
            rating, title = None, None
            for q in scrapers.pegi_queries(g["name"]):
                r = self.f.get(scrapers.pegi_url(q), config.DELAY_PEGI, accept_404=True)
                if r is None:
                    continue
                rating, title = scrapers.pick_pegi(g["name"], scrapers.parse_pegi(r.text))
                if rating:
                    break
            if rating:
                found += 1
            with db.write_lock(), self.conn:
                self.conn.execute(
                    "UPDATE games SET pegi=COALESCE(?, pegi), pegi_title=COALESCE(?, pegi_title), pegi_checked_at=? WHERE id=?",
                    (rating, title, now_iso(), g["id"]))
        self.stats["pegi_checked"] = len(rows)
        self.stats["pegi_found"] = found
