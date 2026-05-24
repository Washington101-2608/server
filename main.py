from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import re
from datetime import datetime

app = FastAPI(title="Malawi News & Security API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── All RSS feeds ─────────────────────────────────────────────────────────────
ALL_FEEDS = [
    ("NYASA TIMES",    "https://www.nyasatimes.com/feed/"),
    ("NATION ONLINE",  "https://mwnation.com/feed/"),
    ("MALAWI 24",      "https://malawi24.com/feed/"),
    ("MARAVI POST",    "https://www.maravipost.com/feed/"),
    ("FACE OF MALAWI", "https://www.faceofmalawi.com/feed/"),
    ("TIMES MW",       "https://times.mw/feed/"),
    ("ZODIAK ONLINE",  "https://www.zodiakmalawi.com/feed"),
    ("MARAVI EXPRESS", "https://maraviexpress.com/feed/"),
    ("MALAWI VOICE",   "https://malawivoice.com/feed/"),
]

SPORTS_FEEDS = [
    ("NYASA TIMES SPORTS",    "https://www.nyasatimes.com/category/sports/feed/"),
    ("MALAWI24 SPORTS",       "https://malawi24.com/category/sports/feed/"),
    ("FACE OF MALAWI SPORTS", "https://faceofmalawi.com/category/sports/feed/"),
]

FOOTBALL_FEEDS = [
    ("NYASA TIMES FOOTBALL", "https://www.nyasatimes.com/category/sports/football/feed/"),
    ("MALAWI24 FOOTBALL",    "https://malawi24.com/category/sports/football/feed/"),
]

SECURITY_KEYWORDS = re.compile(
    r'\b(murder|killed|kill|dead|bodies|body|robbery|robbed|theft|stolen|arrested|arrest|'
    r'assault|attack|attacked|violence|shot|stabbed|stab|rape|raped|kidnap|abduct|missing|'
    r'armed|gun|weapon|machete|burnt|arson|fire|bomb|explosion|flood|cyclone|storm|disaster|'
    r'protest|riot|unrest|gang|criminal|police|court|sentenced|jailed|prison|remand|suspect|'
    r'crackdown|witchcraft|mob|vigilante|corrupt|abuse|fraud|warrant)\b',
    re.IGNORECASE
)

DISTRICT_MAP = {
    "lilongwe": (-13.9626, 33.7741), "blantyre": (-15.7861, 35.0058),
    "zomba": (-15.3833, 35.3167), "mzuzu": (-11.4659, 34.0207),
    "kasungu": (-13.0333, 33.4833), "dedza": (-14.3667, 34.3333),
    "dowa": (-13.6547, 33.9375), "ntcheu": (-14.8167, 34.6333),
    "salima": (-13.7833, 34.4333), "nkhotakota": (-12.9237, 34.2960),
    "mzimba": (-11.9000, 33.6000), "rumphi": (-11.0167, 33.8667),
    "karonga": (-9.9333, 33.9333), "chitipa": (-9.7017, 33.2686),
    "nkhata bay": (-11.6000, 34.3000), "mchinji": (-13.8000, 32.9000),
    "balaka": (-14.9833, 34.9667), "machinga": (-14.9667, 35.5167),
    "mangochi": (-14.4789, 35.2636), "mulanje": (-16.0333, 35.5000),
    "phalombe": (-15.8000, 35.6500), "thyolo": (-16.0667, 35.1333),
    "chiradzulu": (-15.6667, 35.1500), "chikwawa": (-16.0333, 34.8000),
    "nsanje": (-16.9167, 35.2667), "mwanza": (-15.6167, 34.5167),
    "neno": (-15.3833, 34.6667), "ntchisi": (-13.3000, 33.6333),
    "msundwe": (-13.9500, 33.5000), "area 25": (-14.0100, 33.8000),
}

def guess_category(text: str) -> str:
    t = text.lower()
    if re.search(r'flood|drought|cyclone|rain|disaster|storm|earthquake|climate', t): return "disaster"
    if re.search(r'murder|killed|dead|robbery|arrested|assault|attack|violence|shot|stabbed|rape|kidnap|armed|gun|arson|explosion|crime|suspect|court|sentenced|police|crackdown|witchcraft', t): return "crime"
    if re.search(r'election|protest|parliament|government|minister|president|political|party|vote|mcp|utm|dpp|acb|corruption|warrant', t): return "political"
    if re.search(r'football|soccer|sports|team|match|goal|league|flames|bullets|wanderers|silver', t): return "sports"
    return "general"

def severity_from_text(text: str) -> str:
    t = text.lower()
    if re.search(r'murder|killed|dead|bodies|explosion|bomb|rape|kidnap|arson', t): return "critical"
    if re.search(r'robbery|robbed|assault|attack|armed|gun|arrested|crackdown|violence', t): return "high"
    if re.search(r'protest|unrest|riot|flood|cyclone|disaster|warrant|corrupt', t): return "elevated"
    return "low"

def geocode(text: str) -> dict:
    t = text.lower()
    for name, coords in DISTRICT_MAP.items():
        if name in t:
            return {"district": name.title(), "lat": coords[0], "lng": coords[1]}
    return {"district": "Lilongwe", "lat": -13.9626, "lng": 33.7741}

async def fetch_rss(client: httpx.AsyncClient, source: str, feed_url: str, limit: int = 15) -> list:
    """Fetch and parse a single RSS feed — tries rss2json first, then direct XML"""
    # Try rss2json (structured JSON)
    try:
        r = await client.get(
            f"https://api.rss2json.com/v1/api.json?rss_url={feed_url}&count={limit}",
            timeout=10
        )
        d = r.json()
        if d.get("status") == "ok" and d.get("items"):
            items = []
            for item in d["items"]:
                title = item.get("title", "").strip()
                if not title: continue
                desc = re.sub(r'<[^>]+>', '', item.get("description", ""))[:300]
                items.append({
                    "title": title,
                    "source": source,
                    "link": item.get("link", "#"),
                    "published": item.get("pubDate", datetime.utcnow().isoformat()),
                    "description": desc,
                    "category": guess_category(title + " " + desc),
                })
            return items
    except Exception:
        pass

    # Fallback: allorigins proxy + parse XML manually
    try:
        r = await client.get(
            f"https://api.allorigins.win/get?url={feed_url}&timestamp={int(datetime.utcnow().timestamp())}",
            timeout=12
        )
        xml = r.json().get("contents", "")
        if not xml or "<" not in xml:
            return []
        # Simple regex parse for <item> blocks
        items = []
        for m in re.finditer(r'<item>(.*?)</item>', xml, re.DOTALL)[:limit]:
            block = m.group(1)
            title_m = re.search(r'<title[^>]*>(.*?)</title>', block, re.DOTALL)
            link_m  = re.search(r'<link[^>]*>(.*?)</link>', block, re.DOTALL)
            date_m  = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', block, re.DOTALL)
            desc_m  = re.search(r'<description[^>]*>(.*?)</description>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>|\<!\[CDATA\[|\]\]>', '', title_m.group(1) if title_m else "").strip()
            if not title: continue
            desc  = re.sub(r'<[^>]+>|\<!\[CDATA\[|\]\]>', '', desc_m.group(1) if desc_m else "")[:300].strip()
            items.append({
                "title": title,
                "source": source,
                "link": (link_m.group(1) if link_m else "#").strip(),
                "published": (date_m.group(1) if date_m else datetime.utcnow().isoformat()).strip(),
                "description": desc,
                "category": guess_category(title + " " + desc),
            })
        return items
    except Exception:
        return []


@app.get("/")
def home():
    return {
        "api": "Malawi News & Security API",
        "version": "2.0",
        "status": "Running",
        "endpoints": {
            "/news/all":       "All news from 9 sources — newest first",
            "/news/security":  "Security/crime/disaster events only — for SECMON threat map",
            "/news/incidents": "Structured threat incidents with GPS coords — for SECMON map pins",
            "/news/sports":    "Sports news only",
            "/news/football":  "Football/soccer news",
            "/news/nyasatimes":"Nyasa Times only",
            "/news/malawi24":  "Malawi24 only",
            "/news/faceofmalawi": "Face of Malawi only",
            "/news/search?q=": "Search all sources",
            "/news/team/{name}": "Team-specific news",
        }
    }


@app.get("/news/all")
async def all_news():
    """All news from all 9 Malawi sources, sorted newest first"""
    async with httpx.AsyncClient() as client:
        tasks = [fetch_rss(client, src, url) for src, url in ALL_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)

    # Deduplicate
    seen = set()
    deduped = []
    for a in all_articles:
        key = a["title"][:80].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(a)

    deduped.sort(key=lambda x: x.get("published", ""), reverse=True)

    return {
        "total": len(deduped),
        "sources": len(ALL_FEEDS),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "articles": deduped
    }


@app.get("/news/security")
async def security_news():
    """Security, crime, and disaster news only — filtered for SECMON dashboard"""
    data = await all_news()
    security = [
        a for a in data["articles"]
        if SECURITY_KEYWORDS.search(a["title"] + " " + a.get("description", ""))
        or a["category"] in ("crime", "disaster", "political")
    ]
    return {
        "total": len(security),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "articles": security
    }


@app.get("/news/incidents")
async def security_incidents():
    """
    Structured threat incidents with GPS coordinates for SECMON map.
    Each incident has: id, title, description, district, lat, lng,
    date, severity (critical/high/elevated/low), source, verified, category
    """
    sec = await security_news()
    incidents = []

    for i, a in enumerate(sec["articles"]):
        geo = geocode(a["title"] + " " + a.get("description", ""))
        incidents.append({
            "id": f"live-{i}-{int(datetime.utcnow().timestamp())}",
            "title": a["title"][:120],
            "description": a.get("description", "")[:400],
            "district": geo["district"],
            "lat": geo["lat"],
            "lng": geo["lng"],
            "date": a.get("published", "")[:10],
            "severity": severity_from_text(a["title"] + " " + a.get("description", "")),
            "source": a["source"],
            "url": a.get("link", "#"),
            "category": a["category"],
            "verified": False,
            "type": (
                "flood" if a["category"] == "disaster"
                else "armed_robbery" if "robbery" in a["title"].lower() or "armed" in a["title"].lower()
                else "political_violence" if a["category"] == "political"
                else "civil_unrest"
            )
        })

    return {
        "total": len(incidents),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "incidents": incidents
    }


@app.get("/news/sports")
async def sports_news():
    """Sports news from Malawi"""
    async with httpx.AsyncClient() as client:
        tasks = [fetch_rss(client, src, url, 10) for src, url in SPORTS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    all_sports = []
    for r in results:
        if isinstance(r, list):
            all_sports.extend(r)
    all_sports.sort(key=lambda x: x.get("published", ""), reverse=True)
    return {"category": "Sports", "total": len(all_sports), "articles": all_sports}


@app.get("/news/football")
async def football_news():
    """Football/soccer news"""
    async with httpx.AsyncClient() as client:
        tasks = [fetch_rss(client, src, url, 12) for src, url in FOOTBALL_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    all_football = []
    for r in results:
        if isinstance(r, list):
            all_football.extend(r)
    # Merge from sports
    sports = await sports_news()
    for a in sports["articles"]:
        if re.search(r'football|soccer', a["title"], re.I) and a not in all_football:
            all_football.append(a)
    all_football.sort(key=lambda x: x.get("published", ""), reverse=True)
    return {"category": "Football/Soccer", "total": len(all_football), "articles": all_football[:20]}


@app.get("/news/team/{team_name}")
async def team_news(team_name: str):
    TEAMS = {
        "wanderers": "Mighty Wanderers", "bullets": "Nyasa Big Bullets",
        "silver": "Silver Strikers", "flames": "Malawi Flames",
        "civo": "Civo United", "moyale": "Moyale Barracks",
        "blue eagles": "Blue Eagles",
    }
    full_name = TEAMS.get(team_name.lower(), team_name)
    sports = await sports_news()
    results = [a for a in sports["articles"]
               if team_name.lower() in a["title"].lower() or full_name.lower() in a["title"].lower()]
    return {"team": full_name, "total": len(results), "articles": results}


@app.get("/news/nyasatimes")
async def nyasatimes_news():
    async with httpx.AsyncClient() as client:
        items = await fetch_rss(client, "NYASA TIMES", "https://www.nyasatimes.com/feed/", 15)
    return {"source": "Nyasa Times", "total": len(items), "articles": items}


@app.get("/news/malawi24")
async def malawi24_news():
    async with httpx.AsyncClient() as client:
        items = await fetch_rss(client, "MALAWI 24", "https://malawi24.com/feed/", 15)
    return {"source": "Malawi24", "total": len(items), "articles": items}


@app.get("/news/faceofmalawi")
async def faceofmalawi_news():
    async with httpx.AsyncClient() as client:
        items = await fetch_rss(client, "FACE OF MALAWI", "https://www.faceofmalawi.com/feed/", 15)
    return {"source": "Face of Malawi", "total": len(items), "articles": items}


@app.get("/news/search")
async def search_news(q: str):
    data = await all_news()
    results = [a for a in data["articles"]
               if q.lower() in a["title"].lower() or q.lower() in a.get("description", "").lower()]
    return {"search_term": q, "results_count": len(results), "articles": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
