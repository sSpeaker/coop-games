"""Parser tests on markup captured from the live sites, plus an API smoke test on a temp database."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["UPDATE_ON_EMPTY_START"] = "0"
os.environ["UPDATE_INTERVAL_HOURS"] = "0"

from app import db, scrapers, updater  # noqa: E402
from app.text import norm, parse_date, strip_edition  # noqa: E402

OC_BROWSE = """<div class="row no-gutters py-2 game-row align-items-center"><div class="rank"> 2. </div>
<div class="score col-auto"><app-score-orb><div class="score-orb"><div class="inner-orb small-orb"> 93 </div></div></app-score-orb></div>
<div class="box-art"><a href="/game/17574/vampire-survivors-ode-to-castlevania"><img class="img-fluid" alt="Vampire Survivors: Ode to Castlevania" src="https://img.opencritic.com/game/17574/bHZ6hqFP.jpg"></a></div>
<div class="game-name col ml-2"><a href="/game/17574/vampire-survivors-ode-to-castlevania">Vampire Survivors: Ode to Castlevania</a></div>
<div class="genres mx-4"> </div><div class="first-release-date col-auto show-year"><span>Oct 31, 2024</span></div></div>
<div class="row no-gutters py-2 game-row align-items-center"><div class="score col-auto"><app-score-orb><div class="score-orb"><div class="inner-orb small-orb"> -1 </div></div></app-score-orb></div>
<div class="game-name col ml-2"><a href="/game/1/test">Test Game</a></div><div class="genres mx-4"> Action, RPG </div>
<div class="first-release-date col-auto show-year"><span>Jan 2, 2020</span></div></div>"""

OC_GAME = """<html><head><meta property="og:image" content="https://img.opencritic.com/game/18192/o/ruIEYvxC.jpg">
<script type="application/ld+json">{"@context":"http://schema.org","@type":"VideoGame","name":"Split Fiction",
"description":"Embrace mind-blowing moments","genre":["Action","Adventure"],"datePublished":"2025-03-06T00:00:00.000Z",
"image":"https://img.opencritic.com/game/18192/o/N3LM8Kn2.jpg",
"trailer":[{"@type":"VideoObject","name":"Split Fiction | Official Co-op Gameplay Trailer","url":"https://youtube.com/watch?v=0TlySOphMuo","embedUrl":"https://www.youtube.com/embed/0TlySOphMuo"}],
"aggregateRating":{"@type":"AggregateRating","ratingValue":91}}</script>
<script type="application/ld+json">{"@context":"http://schema.org","@type":"BreadcrumbList"}</script></head>
<body><img width="100%" src="https://img.opencritic.com/game/18192/ECFw8ous.jpg" alt="Split Fiction header image"></body></html>"""

COOPT = """<table><tr class="result_row" id="8971" title="killallzombies">
<td><strong>#KILLALLZOMBIES</strong>&nbsp;<a href="http://www.co-optimus.com/game/8971/pc/killallzombies.html"></a><label>Twin Stick Shooter</label></td>
<td>0</td><td>2</td><td>0</td>
<td><a title="2 Players in Co-Op" class="2players-icon features-icon"></a><a title="Supports Couch Co-Op" class="couch-icon features-icon"></a><a title="Supports Split-Screen" class="features-icon"></a></td>
<td></td><td><span class="released">08/10/2016</span></td></tr></table>
<ul><li><a href="javascript: void(0);" onclick="setPage('2')">Next</a></li><li><a onclick="setPage('222');">Last</a></li></ul>"""

PEGI_HTML = """<div id="results"><article class="game"><div class="game-content__header-rating">
<img src="https://rating.pegi.info/assets/images/games/age_threshold_icons/16.png" alt="age rating 16"></div>
<div class="game-content__header-title"><h3>Split Fiction</h3></div></article>
<article class="game"><div class="game-content__header-rating"><img src="https://rating.pegi.info/x/12.png"></div><h3>Split Fiction Deluxe Edition</h3></article></div>"""


def test_text():
    assert norm("Baldur’s Gate 3: Héroes & Co!") == "baldurs gate 3 heroes and co"
    assert strip_edition("Diablo IV - Deluxe Edition") == "diablo iv"
    assert parse_date("Oct 31, 2024") == "2024-10-31"
    assert parse_date("08/10/2016") == "2016-08-10"
    assert parse_date("2025-03-06T00:00:00.000Z") == "2025-03-06"


def test_oc_browse():
    rows = scrapers.parse_oc_browse(OC_BROWSE)
    assert rows[0] == {"oc_id": 17574, "slug": "vampire-survivors-ode-to-castlevania", "name": "Vampire Survivors: Ode to Castlevania",
                       "score": 93, "genres": [], "release_date": "2024-10-31", "image": "https://img.opencritic.com/game/17574/bHZ6hqFP.jpg"}
    assert rows[1]["score"] is None and rows[1]["genres"] == ["Action", "RPG"]


def test_oc_game():
    d = scrapers.parse_oc_game(OC_GAME)
    assert d["score"] == 91 and d["genres"] == ["Action", "Adventure"]
    assert d["trailers"] == [{"id": "0TlySOphMuo", "name": "Split Fiction | Official Co-op Gameplay Trailer"}]
    assert d["image"].endswith("ruIEYvxC.jpg") and d["banner"].endswith("ECFw8ous.jpg")
    assert d["release_date"] == "2025-03-06"


def test_coopt():
    rows, last = scrapers.parse_coopt_page(COOPT)
    assert last == 222
    r = rows[0]
    assert (r["coopt_id"], r["title"], r["genre"], r["online"], r["couch"], r["lan"]) == (8971, "#KILLALLZOMBIES", "Twin Stick Shooter", 0, 2, 0)
    assert r["features"] == ["Couch", "Split-Screen"] and r["players"] == 2 and r["release"] == "2016-08-10"
    assert scrapers.coopt_genres("Twin Stick Shooter") == ["Action", "Arcade"]


def test_pegi():
    res = scrapers.parse_pegi(PEGI_HTML)
    assert res == [{"title": "Split Fiction", "rating": 16}, {"title": "Split Fiction Deluxe Edition", "rating": 12}]
    assert scrapers.pick_pegi("Split Fiction", res) == (16, "Split Fiction")
    assert scrapers.pick_pegi("Call of Duty: Black Ops", [{"title": "Call of Duty: Black Ops 6", "rating": 18}]) == (None, None)
    assert scrapers.pegi_queries("Fly Together!") == ["Fly Together!", "Fly Together"]


def seed():
    db.init()
    conn = db.connect()
    with conn:
        games = [
            (1, "a", "Alpha Co-op", 90, "2020-05-01", "Action, RPG", 16, 4, 0, 0),
            (2, "b", "Beta Couch", 80, "2018-01-01", "Platformer", 7, 0, 4, 0),
            (3, "c", "Gamma Party", None, "2026-12-01", "Action", None, 8, 8, 8),
        ]
        for gid, slug, name, score, date, genres, pegi, on, co, lan in games:
            conn.execute(
                """INSERT INTO games(id, slug, name, norm, score, release_date, genres, pegi, online, couch, lan, features, trailers)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (gid, slug, name, norm(name), score, date, genres, pegi, on, co, lan, json.dumps(["Split-Screen"]),
                 json.dumps([{"id": "0TlySOphMuo", "name": "T"}])))
            conn.execute("INSERT INTO game_platform VALUES(?, 'PC')", (gid,))
        conn.execute("INSERT INTO game_platform VALUES(2, 'Switch')")
        conn.execute("""INSERT INTO coopt(coopt_id, platform, title, norm, genre, online, couch, lan, features, release, oc_id)
                        VALUES(10, 'PC', 'Alpha Co-op', 'alpha co op', 'Action', 4, 0, 0, '[]', '2020-05-01', 1)""")
    job = updater.Job(conn, None, False)
    job.rebuild_genre_index()
    conn.close()


def test_api():
    from fastapi.testclient import TestClient
    from app.main import app
    seed()
    with TestClient(app) as c:
        m = c.get("/api/meta").json()
        assert {g["name"]: g["count"] for g in m["genres"]} == {"Action": 2, "Platformer": 1, "RPG": 1}
        assert (m["year_min"], m["year_max"]) == (2018, 2026)
        names = lambda r: [x["name"] for x in r.json()["items"]]  # noqa: E731
        assert names(c.get("/api/games?sort=score&dir=desc")) == ["Alpha Co-op", "Beta Couch", "Gamma Party"]
        assert names(c.get("/api/games?sort=score&dir=asc")) == ["Beta Couch", "Alpha Co-op", "Gamma Party"]
        assert names(c.get("/api/games?sort=date&dir=desc")) == ["Gamma Party", "Alpha Co-op", "Beta Couch"]
        assert names(c.get("/api/games?genres=Action&sort=name&dir=asc")) == ["Alpha Co-op", "Gamma Party"]
        assert names(c.get("/api/games?genres=Action,RPG")) == ["Alpha Co-op"]
        assert names(c.get("/api/games?couch=true")) == ["Beta Couch", "Gamma Party"]
        assert names(c.get("/api/games?max_pegi=12")) == ["Beta Couch"]
        assert names(c.get("/api/games?max_pegi=12&include_unrated=true")) == ["Beta Couch", "Gamma Party"]
        assert names(c.get("/api/games?platforms=Switch")) == ["Beta Couch"]
        assert names(c.get("/api/games?year_from=2019&year_to=2021")) == ["Alpha Co-op"]
        assert names(c.get("/api/games?q=co op")) == ["Alpha Co-op"]
        assert c.put("/api/played/2").json() == {"played": True}
        assert names(c.get("/api/games?hide_played=true")) == ["Alpha Co-op", "Gamma Party"]
        assert names(c.get("/api/games?only_played=true")) == ["Beta Couch"]
        g = c.get("/api/games/1").json()
        assert g["coop"][0]["online"] == 4 and g["trailers"][0]["id"] == "0TlySOphMuo"
        assert c.get("/api/status").json()["played"] == 1
        assert c.get("/").status_code == 200 and c.get("/static/app.js").status_code == 200


class _BlockedFetcher:
    """Fetcher stand-in whose every request gets the 403 Co-optimus returns from Cloudflare."""

    def get(self, url, delay, params=None, accept_404=False):
        import httpx
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("403 Forbidden", request=req, response=httpx.Response(403, request=req))


def test_cooptimus_blocked_keeps_player_counts():
    conn = db.connect()
    with conn:
        conn.execute("INSERT OR REPLACE INTO catalog(oc_id, slug, name, norm, score, release_date, genres) "
                     "VALUES(1, 'a', 'Alpha Co-op', 'alpha co op', 91, '2020-05-01', 'Action')")
        conn.execute("INSERT OR REPLACE INTO catalog_platform(oc_id, platform, oc_coop) VALUES(1, 'PC', 1)")
    job = updater.Job(conn, _BlockedFetcher(), False)
    job.crawl_cooptimus()  # must not raise
    assert job.coopt_ok is False and job.stats["coopt_error"].startswith("403 ")
    job.build_games()
    row = conn.execute("SELECT online, features, score FROM games WHERE id=1").fetchone()
    assert row["online"] == 4 and "Split-Screen" in row["features"] and row["score"] == 91
    conn.close()
