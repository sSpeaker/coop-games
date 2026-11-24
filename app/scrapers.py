"""HTTP fetching and HTML parsing for OpenCritic, Co-optimus, pegi.info and Steam."""
import json
import logging
import re
import time
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from . import config
from .text import norm, parse_date, strip_edition

log = logging.getLogger("scrapers")

OC = "https://opencritic.com"
COOPT = "https://www.co-optimus.com"
PEGI = "https://pegi.info"
STEAM = "https://store.steampowered.com"


try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # pragma: no cover - optional dependency
    cffi_requests = None


class HTTPStatusError(Exception):
    def __init__(self, url, status, body=""):
        super().__init__(f"GET {url} -> HTTP {status}: {body[:120]!r}")
        self.status = status


class Fetcher:
    """Polite HTTP client: per-host delay, retries, 429 backoff.

    Uses curl_cffi with a Chrome TLS/HTTP2 fingerprint when available (Cloudflare on co-optimus.com
    rejects plain Python clients with 403), otherwise httpx.
    """

    def __init__(self, stop_flag=None):
        self.headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if cffi_requests and config.IMPERSONATE:
            self.session = cffi_requests.Session(impersonate=config.IMPERSONATE, timeout=30)
            self.kind = "curl_cffi"
        else:
            self.session = httpx.Client(headers=self.headers, timeout=30, follow_redirects=True)
            self.kind = "httpx"
        self.last = {}
        self.warmed = set()
        self.stop_flag = stop_flag or (lambda: False)
        log.info("HTTP client: %s", self.kind)

    def close(self):
        self.session.close()

    def _wait(self, host, delay):
        elapsed = time.monotonic() - self.last.get(host, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last[host] = time.monotonic()

    def _request(self, url, params, headers):
        if self.kind == "curl_cffi":
            # Let curl_cffi send its own Chrome User-Agent so headers match the TLS fingerprint.
            h = {k: v for k, v in headers.items() if k != "User-Agent"}
            return self.session.get(url, params=params, headers=h, allow_redirects=True)
        return self.session.get(url, params=params, headers=headers)

    def warm_up(self, url, delay):
        """Load a normal page first so the site sets its cookies before XHR-style requests."""
        host = httpx.URL(url).host
        if host in self.warmed:
            return
        self.warmed.add(host)
        try:
            self.get(url, delay)
        except Exception as e:  # noqa: BLE001
            log.warning("warm-up %s failed: %s", url, e)

    def get(self, url, delay, params=None, accept_404=False, headers=None):
        host = httpx.URL(url).host
        h = dict(self.headers, **(headers or {}))
        last_status = None
        for attempt in range(6):
            if self.stop_flag():
                raise StopRequested()
            self._wait(host, delay)
            try:
                r = self._request(url, params, h)
            except Exception as e:  # noqa: BLE001 - network errors from either client
                log.warning("GET %s failed: %s", url, e)
                time.sleep(5 * (attempt + 1))
                continue
            last_status = r.status_code
            if r.status_code == 429 or r.status_code >= 500:
                wait = config.BACKOFF_429 if r.status_code == 429 else 10 * (attempt + 1)
                log.warning("GET %s -> %s, sleeping %ss", url, r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code == 404 and accept_404:
                return None
            if r.status_code == 403 and attempt < 2:
                log.warning("GET %s -> 403, retrying", url)
                time.sleep(15)
                continue
            if r.status_code >= 400:
                raise HTTPStatusError(url, r.status_code, r.text or "")
            return r
        raise HTTPStatusError(url, last_status or 0, "failed after retries")


class StopRequested(Exception):
    pass


# ---------------------------------------------------------------- OpenCritic

def oc_browse_url(platform_slug, page, coop):
    return f"{OC}/browse/{platform_slug}/all-time/date{'/co-op' if coop else ''}?page={page}"


_GAME_HREF = re.compile(r"^/game/(\d+)/([^/?#]+)")


def parse_oc_browse(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select(".game-row"):
        a = row.select_one(".game-name a")
        if not a:
            continue
        m = _GAME_HREF.match(a.get("href", ""))
        if not m:
            continue
        orb = row.select_one(".inner-orb")
        score = None
        if orb:
            t = orb.get_text(strip=True)
            if re.fullmatch(r"\d+", t):
                score = int(t)
        genres_el = row.select_one(".genres")
        genres = [g.strip() for g in genres_el.get_text(" ", strip=True).split(",")] if genres_el else []
        date_el = row.select_one(".first-release-date")
        img = row.select_one(".box-art img")
        out.append({
            "oc_id": int(m.group(1)),
            "slug": m.group(2),
            "name": a.get_text(strip=True),
            "score": score,
            "genres": [g for g in genres if g],
            "release_date": parse_date(date_el.get_text(" ", strip=True)) if date_el else None,
            "image": img.get("src") if img else None,
        })
    return out


_YT_ID = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")


def parse_oc_game(html):
    soup = BeautifulSoup(html, "lxml")
    data = {"genres": [], "trailers": []}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or obj.get("@type") != "VideoGame":
            continue
        data["name"] = obj.get("name")
        data["description"] = (obj.get("description") or "").strip() or None
        g = obj.get("genre") or []
        data["genres"] = [g] if isinstance(g, str) else [x for x in g if x]
        data["release_date"] = parse_date(obj.get("datePublished"))
        rating = obj.get("aggregateRating") or {}
        rv = rating.get("ratingValue")
        if isinstance(rv, (int, float)) and rv > 0:
            data["score"] = round(rv)
        data["box_art"] = obj.get("image")
        trailers = obj.get("trailer") or []
        if isinstance(trailers, dict):
            trailers = [trailers]
        for t in trailers:
            m = _YT_ID.search((t.get("embedUrl") or "") + " " + (t.get("url") or ""))
            if m:
                data["trailers"].append({"id": m.group(1), "name": t.get("name") or ""})
        break
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        data["image"] = og["content"]
    for img in soup.find_all("img"):
        if (img.get("alt") or "").endswith("header image") and "img.opencritic.com/game/" in (img.get("src") or ""):
            data["banner"] = img["src"]
            break
    return data


# ---------------------------------------------------------------- Metacritic

METACRITIC = "https://www.metacritic.com"


def mc_slugs(name):
    """Candidate Metacritic URL slugs: full title, then without edition words."""
    def slug(s, amp):
        s = s.replace("'", "").replace("’", "").replace("&", amp)
        return norm(s).replace(" ", "-")
    out = []
    # Metacritic drops "&" ("ratchet-clank-rift-apart"); some older slugs spell it out.
    for s in (slug(name, " "), slug(name, " and "), strip_edition(name).replace(" ", "-")):
        if s and s not in out:
            out.append(s)
    return out


def parse_mc_game(html):
    """Name, release date and Metascore from the VideoGame ld+json of a Metacritic game page."""
    soup = BeautifulSoup(html, "lxml")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or obj.get("@type") != "VideoGame":
            continue
        rating = obj.get("aggregateRating") or {}
        rv = rating.get("ratingValue")
        return {
            "name": obj.get("name") or "",
            "release_date": parse_date(obj.get("datePublished")),
            "metascore": round(rv) if isinstance(rv, (int, float)) and rv > 0 else None,
            "url": obj.get("url"),
        }
    return None


# ---------------------------------------------------------------- Co-optimus

def coopt_url(system_id, page):
    return f"{COOPT}/ajax/ajax_games.php?system={system_id}&page={page}"


COOPT_XHR_HEADERS = {
    "Referer": f"{COOPT}/games.php",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
}


def _int(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else 0


def parse_coopt_page(html):
    """Rows of a Co-optimus list filtered by one system, plus the last page number."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tr.result_row"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7:
            continue
        strong = tds[0].find("strong")
        label = tds[0].find("label")
        feats = []
        players = 0
        for a in tds[4].select(".features-icon"):
            title = (a.get("title") or "").strip()
            m = re.match(r"(\d+) Players? in Co-Op", title)
            if m:
                players = int(m.group(1))
                continue
            title = re.sub(r"^Supports\s+", "", title)
            title = re.sub(r"\s+Co-Op$", "", title)
            if title:
                feats.append(title)
        rid = tr.get("id", "")
        if not rid.isdigit() or not strong:
            continue
        rows.append({
            "coopt_id": int(rid),
            "title": strong.get_text(strip=True),
            "genre": label.get_text(strip=True) if label else None,
            "online": _int(tds[1].get_text()),
            "couch": _int(tds[2].get_text()),
            "lan": _int(tds[3].get_text()),
            "features": feats,
            "players": players,
            "release": parse_date(tds[6].get_text(" ", strip=True)),
        })
    last = 1
    for a in soup.find_all("a", onclick=True):
        m = re.search(r"setPage\('(\d+)'\)", a["onclick"])
        if m:
            last = max(last, int(m.group(1)))
    return rows, last


# Co-optimus genre label -> OpenCritic genres
COOPT_GENRES = {
    "action": ["Action"],
    "action rpg": ["RPG", "Action"],
    "action/adventure": ["Action", "Adventure"],
    "adventure": ["Adventure"],
    "arcade": ["Arcade"],
    "beat-em-up": ["Fighting", "Action"],
    "board game": ["Card Game"],
    "card game": ["Card Game"],
    "fighting": ["Fighting"],
    "first person shooter": ["First-Person Shooter"],
    "third person shooter": ["Third-Person Shooter"],
    "tactical shooter": ["First-Person Shooter"],
    "horror": ["Horror"],
    "survival horror": ["Horror", "Survival"],
    "survival": ["Survival"],
    "mmo": ["MMO"],
    "mmorpg": ["MMO", "RPG"],
    "music": ["Music"],
    "rhythm": ["Music"],
    "party": ["Arcade"],
    "platformer": ["Platformer"],
    "platform shooter": ["Platformer", "Action"],
    "puzzle": ["Puzzle"],
    "racing": ["Racing"],
    "rpg": ["RPG"],
    "rts": ["Real-Time Strategy"],
    "real-time strategy": ["Real-Time Strategy"],
    "roguelike": ["Roguelike"],
    "sandbox": ["Creation"],
    "shmup": ["Arcade", "Action"],
    "simulation": ["Simulation"],
    "sports": ["Sports"],
    "strategy": ["Strategy"],
    "tower defense": ["Strategy"],
    "turn-based strategy": ["Turn-Based Strategy"],
    "twin stick shooter": ["Action", "Arcade"],
    "vehicle combat": ["Vehicle Combat"],
}


def coopt_genres(label):
    return COOPT_GENRES.get((label or "").strip().lower(), [])


# ---------------------------------------------------------------- PEGI

def pegi_url(query):
    return f"{PEGI}/search-pegi?q={quote(query)}"


def parse_pegi(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for art in soup.select("#results article.game"):
        h3 = art.find("h3")
        img = art.select_one(".game-content__header-rating img")
        if not h3 or not img:
            continue
        m = re.search(r"/(\d+)\.png", img.get("src", ""))
        if m:
            out.append({"title": h3.get_text(strip=True), "rating": int(m.group(1))})
    return out


def pick_pegi(name, results):
    """Exact or edition-stripped title match only; most common rating among matches wins, ties go to the higher one."""
    def mode(items):
        counts = {}
        for x in items:
            counts[x["rating"]] = counts.get(x["rating"], 0) + 1
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

    n, b = norm(name), strip_edition(name)
    exact = [r for r in results if norm(r["title"]) == n]
    if exact:
        return mode(exact), exact[0]["title"]
    if b:
        stripped = [r for r in results if strip_edition(r["title"]) == b]
        if stripped:
            return mode(stripped), stripped[0]["title"]
    return None, None


def pegi_queries(name):
    """Search phrases: full title, then title without punctuation that pegi.info search trips on."""
    q1 = name.strip()
    q2 = re.sub(r"[:\-–—!?®™]", " ", q1)
    q2 = re.sub(r"\s+", " ", q2).strip()
    return [q1] if q2 == q1 else [q1, q2]


# ---------------------------------------------------------------- Steam (genre fallback)

STEAM_GENRES = {
    "Action": ["Action"], "Adventure": ["Adventure"], "RPG": ["RPG"], "Strategy": ["Strategy"],
    "Simulation": ["Simulation"], "Sports": ["Sports"], "Racing": ["Racing"],
    "Massively Multiplayer": ["MMO"],
}


def parse_steam_search(text, name):
    try:
        items = json.loads(text).get("items", [])
    except ValueError:
        return None
    n = norm(name)
    for it in items:
        if norm(it.get("name", "")) == n:
            return it.get("id")
    return None


def parse_steam_genres(text, appid):
    try:
        obj = json.loads(text).get(str(appid), {})
    except ValueError:
        return []
    if not obj.get("success"):
        return []
    out = []
    for g in obj.get("data", {}).get("genres", []):
        for x in STEAM_GENRES.get(g.get("description", ""), []):
            if x not in out:
                out.append(x)
    return out
