import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, scrapers, seed, updater

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = FastAPI(title="Co-op Games")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def scheduler():
    """Start updates on an empty DB and every UPDATE_INTERVAL_HOURS afterwards."""
    time.sleep(5)
    while True:
        try:
            conn = db.connect()
            count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            last = db.get_meta(conn, "last_update_at")
            interrupted = db.get_meta(conn, "last_update_result") == "interrupted"
            conn.close()
            due = False
            if interrupted:
                # A job cut off by a restart resumes; finished steps skip already fetched data.
                due = True
            elif not last:
                # Never updated yet (empty or freshly seeded database)
                due = config.UPDATE_ON_EMPTY_START
            elif config.UPDATE_INTERVAL_HOURS > 0:
                age = datetime.now(timezone.utc) - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                due = age.total_seconds() >= config.UPDATE_INTERVAL_HOURS * 3600
            if due and not updater.is_running():
                log.info("scheduled update starting")
                updater.start_background()
        except Exception:  # noqa: BLE001
            log.exception("scheduler error")
        time.sleep(300)


@app.on_event("startup")
def startup():
    db.init()
    conn = db.connect()
    seed.import_if_empty(conn)
    # A job interrupted by a restart leaves state=running; reset it.
    with conn:
        if db.get_meta(conn, "update_state") == "running":
            db.set_meta(conn, "update_state", "idle")
            db.set_meta(conn, "last_update_result", "interrupted")
    conn.close()
    threading.Thread(target=scheduler, daemon=True, name="scheduler").start()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


def _game_dict(r, played, want=frozenset(), skip=frozenset()):
    return {
        "id": r["id"],
        "name": r["name"],
        "score": r["score"],
        "metascore": r["metascore"],
        "pegi": r["pegi"],
        "release_date": r["release_date"],
        "genres": [x for x in (r["genre_list"] or "").split("|") if x],
        "platforms": sorted([x for x in (r["platform_list"] or "").split("|") if x], key=_plat_order),
        "image": r["image"] or r["banner"],
        "online": r["online"],
        "couch": r["couch"],
        "lan": r["lan"],
        "features": json.loads(r["features"] or "[]"),
        "played": r["id"] in played,
        "want": r["id"] in want,
        "skip": r["id"] in skip,
    }


def _plat_order(p):
    keys = list(config.PLATFORMS)
    return keys.index(p) if p in keys else 99


BASE_SELECT = """
SELECT g.*,
  (SELECT group_concat(genre, '|') FROM game_genre WHERE game_id=g.id) AS genre_list,
  (SELECT group_concat(platform, '|') FROM game_platform WHERE game_id=g.id) AS platform_list
FROM games g
"""


@app.get("/api/meta")
def meta():
    conn = db.connect()
    try:
        years = conn.execute(
            "SELECT MIN(substr(release_date,1,4)), MAX(substr(release_date,1,4)) FROM games WHERE release_date IS NOT NULL"
        ).fetchone()
        genres = []
        for r in conn.execute(
            """SELECT genre, COUNT(*) AS n FROM game_genre WHERE game_id NOT IN (SELECT game_id FROM skip)
               GROUP BY genre ORDER BY genre='Other', genre"""
        ).fetchall():
            imgs = [x[0] for x in conn.execute(
                """SELECT COALESCE(g.banner, g.image) FROM games g JOIN game_genre gg ON gg.game_id=g.id
                   WHERE gg.genre=? AND COALESCE(g.banner, g.image) IS NOT NULL
                     AND g.id NOT IN (SELECT game_id FROM skip)
                   ORDER BY g.score IS NULL, g.score DESC LIMIT 4""", (r["genre"],))]
            genres.append({"name": r["genre"], "count": r["n"], "images": imgs})
        return {
            "platforms": list(config.PLATFORMS),
            "genres": genres,
            "year_min": int(years[0]) if years[0] else None,
            "year_max": int(years[1]) if years[1] else None,
        }
    finally:
        conn.close()


@app.get("/api/games")
def games(
    q: str = "",
    genres: str = "",
    online: bool = False,
    couch: bool = False,
    lan: bool = False,
    max_pegi: int = 0,
    include_unrated: bool = False,
    platforms: str = "",
    year_from: int = 0,
    year_to: int = 0,
    hide_played: bool = False,
    only_played: bool = False,
    hide_want: bool = False,
    only_want: bool = False,
    show_skipped: bool = False,
    only_skipped: bool = False,
    sort: str = Query("score", pattern="^(score|metascore|name|date)$"),
    dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    where, args = [], []
    for term in q.lower().split():
        where.append("g.name LIKE ? ESCAPE '\\'")
        args.append("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    for gname in [x for x in genres.split(",") if x]:
        where.append("EXISTS (SELECT 1 FROM game_genre WHERE game_id=g.id AND genre=?)")
        args.append(gname)
    if online:
        where.append("g.online > 0")
    if couch:
        where.append("g.couch > 0")
    if lan:
        where.append("g.lan > 0")
    if max_pegi:
        where.append("(g.pegi <= ?" + (" OR g.pegi IS NULL)" if include_unrated else ")"))
        args.append(max_pegi)
    plats = [x for x in platforms.split(",") if x]
    if plats:
        where.append("EXISTS (SELECT 1 FROM game_platform WHERE game_id=g.id AND platform IN (%s))" % ",".join("?" * len(plats)))
        args += plats
    if year_from:
        where.append("g.release_date >= ?")
        args.append(f"{year_from:04d}-01-01")
    if year_to:
        where.append("g.release_date <= ?")
        args.append(f"{year_to:04d}-12-31")
    if hide_played:
        where.append("g.id NOT IN (SELECT game_id FROM played)")
    if only_played:
        where.append("g.id IN (SELECT game_id FROM played)")
    if hide_want:
        where.append("g.id NOT IN (SELECT game_id FROM want)")
    if only_want:
        where.append("g.id IN (SELECT game_id FROM want)")
    if only_skipped:
        where.append("g.id IN (SELECT game_id FROM skip)")
    elif not show_skipped:
        where.append("g.id NOT IN (SELECT game_id FROM skip)")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    d = "DESC" if dir == "desc" else "ASC"
    order = {
        "score": f"g.score IS NULL, g.score {d}, g.name COLLATE NOCASE ASC",
        "metascore": f"g.metascore IS NULL, g.metascore {d}, g.name COLLATE NOCASE ASC",
        "name": f"g.name COLLATE NOCASE {d}",
        "date": f"g.release_date IS NULL, g.release_date {d}, g.name COLLATE NOCASE ASC",
    }[sort]
    conn = db.connect()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM games g{wsql}", args).fetchone()[0]
        rows = conn.execute(f"{BASE_SELECT}{wsql} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        played = {r[0] for r in conn.execute("SELECT game_id FROM played")}
        want = {r[0] for r in conn.execute("SELECT game_id FROM want")}
        skip = {r[0] for r in conn.execute("SELECT game_id FROM skip")}
        return {"total": total, "items": [_game_dict(r, played, want, skip) for r in rows]}
    finally:
        conn.close()


@app.get("/api/games/{gid}")
def game(gid: int):
    conn = db.connect()
    try:
        r = conn.execute(f"{BASE_SELECT} WHERE g.id=?", (gid,)).fetchone()
        if not r:
            raise HTTPException(404)
        played = {x[0] for x in conn.execute("SELECT game_id FROM played WHERE game_id=?", (gid,))}
        want = {x[0] for x in conn.execute("SELECT game_id FROM want WHERE game_id=?", (gid,))}
        skip = {x[0] for x in conn.execute("SELECT game_id FROM skip WHERE game_id=?", (gid,))}
        out = _game_dict(r, played, want, skip)
        out.update({
            "description": r["description"],
            "banner": r["banner"] or r["image"],
            "trailers": json.loads(r["trailers"] or "[]"),
            "pegi_title": r["pegi_title"],
            "mc_url": r["mc_url"],
            "url": f"https://opencritic.com/game/{r['id']}/{r['slug']}",
            "stores": scrapers.store_links(r["name"], out["platforms"], r["steam_appid"], r["eshop_url"]),
            "coop": [
                {"platform": c["platform"], "online": c["online"], "couch": c["couch"], "lan": c["lan"],
                 "features": json.loads(c["features"] or "[]"),
                 "url": f"https://www.co-optimus.com/game/{c['coopt_id']}/"}
                for c in sorted(conn.execute("SELECT * FROM coopt WHERE oc_id=?", (gid,)).fetchall(),
                                key=lambda c: _plat_order(c["platform"]))
            ],
        })
        return out
    finally:
        conn.close()


@app.put("/api/played/{gid}")
def mark_played(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            if not conn.execute("SELECT 1 FROM games WHERE id=?", (gid,)).fetchone():
                raise HTTPException(404)
            conn.execute("INSERT OR IGNORE INTO played(game_id, played_at) VALUES(?, ?)", (gid, updater.now_iso()))
            # A played game leaves the want-to-play list.
            conn.execute("DELETE FROM want WHERE game_id=?", (gid,))
        return {"played": True, "want": False}
    finally:
        conn.close()


@app.delete("/api/played/{gid}")
def unmark_played(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            conn.execute("DELETE FROM played WHERE game_id=?", (gid,))
        return {"played": False}
    finally:
        conn.close()


@app.put("/api/want/{gid}")
def mark_want(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            if not conn.execute("SELECT 1 FROM games WHERE id=?", (gid,)).fetchone():
                raise HTTPException(404)
            conn.execute("INSERT OR IGNORE INTO want(game_id, added_at) VALUES(?, ?)", (gid, updater.now_iso()))
            conn.execute("DELETE FROM skip WHERE game_id=?", (gid,))  # wanting a game undoes "not interested"
        return {"want": True, "skip": False}
    finally:
        conn.close()


@app.delete("/api/want/{gid}")
def unmark_want(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            conn.execute("DELETE FROM want WHERE game_id=?", (gid,))
        return {"want": False}
    finally:
        conn.close()


@app.put("/api/skip/{gid}")
def mark_skip(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            if not conn.execute("SELECT 1 FROM games WHERE id=?", (gid,)).fetchone():
                raise HTTPException(404)
            conn.execute("INSERT OR IGNORE INTO skip(game_id, added_at) VALUES(?, ?)", (gid, updater.now_iso()))
            conn.execute("DELETE FROM want WHERE game_id=?", (gid,))  # not interested leaves the want list
        return {"skip": True, "want": False}
    finally:
        conn.close()


@app.delete("/api/skip/{gid}")
def unmark_skip(gid: int):
    conn = db.connect()
    try:
        with db.write_lock(), conn:
            conn.execute("DELETE FROM skip WHERE game_id=?", (gid,))
        return {"skip": False}
    finally:
        conn.close()


@app.get("/api/status")
def status():
    conn = db.connect()
    try:
        m = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        return {
            "games": conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
            "played": conn.execute("SELECT COUNT(*) FROM played").fetchone()[0],
            "want": conn.execute("SELECT COUNT(*) FROM want").fetchone()[0],
            "skip": conn.execute("SELECT COUNT(*) FROM skip").fetchone()[0],
            "running": updater.is_running(),
            "step": m.get("update_step"),
            "done": m.get("update_done"),
            "total": m.get("update_total"),
            "started_at": m.get("update_started_at"),
            "last_update_at": m.get("last_update_at"),
            "last_result": m.get("last_update_result"),
            "last_stats": json.loads(m.get("last_update_stats") or "{}"),
            "interval_hours": config.UPDATE_INTERVAL_HOURS,
        }
    finally:
        conn.close()


@app.post("/api/update")
def start_update(full: bool = False):
    return {"started": updater.start_background(full=full)}


@app.post("/api/import/cooptimus")
async def import_cooptimus(request: Request):
    """Accepts the coopt.json file produced by the browser snippet on the Data page."""
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Body is not JSON")
    if isinstance(payload, dict):
        payload = payload.get("rows", [])
    if not isinstance(payload, list) or not payload:
        raise HTTPException(400, "Expected a non-empty JSON array")
    if not updater.start_import(payload):
        raise HTTPException(409, "An update is running; try again when it finishes")
    return {"started": True, "rows": len(payload)}


@app.post("/api/update/stop")
def stop_update():
    updater.request_stop()
    return {"stopping": updater.is_running()}
