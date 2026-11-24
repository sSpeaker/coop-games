"""One-time import of the curated Co-op sheet (app/seed/games.csv) into an empty database."""
import csv
import logging
import os

from . import db
from .text import norm
from .updater import now_iso

log = logging.getLogger("seed")
SEED_CSV = os.path.join(os.path.dirname(__file__), "seed", "games.csv")


def import_if_empty(conn):
    if conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] or not os.path.exists(SEED_CSV):
        return 0
    ts = now_iso()
    n = 0
    with open(SEED_CSV, newline="", encoding="utf-8") as f, db.write_lock(), conn:
        for r in csv.DictReader(f):
            gid = int(r["id"])
            score = int(r["score"]) if r["score"] else None
            pegi = int(r["pegi"]) if r["pegi"] else None
            conn.execute(
                """INSERT OR IGNORE INTO games(id, slug, name, norm, score, release_date, genres, pegi, pegi_title,
                                               pegi_checked_at, genre_checked_at, source, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (gid, r["slug"], r["name"], norm(r["name"]), score, r["release_date"] or None, r["genres"], pegi,
                 "seed" if pegi else None, ts, ts, "seed", ts),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO game_platform(game_id, platform) VALUES(?,?)",
                [(gid, p) for p in r["platforms"].split("|") if p],
            )
            for g in [x.strip() for x in r["genres"].split(",") if x.strip()]:
                conn.execute("INSERT OR IGNORE INTO game_genre(game_id, genre) VALUES(?,?)", (gid, g))
            n += 1
    log.info("seeded %d games from %s", n, SEED_CSV)
    return n
