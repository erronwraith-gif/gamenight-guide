#!/usr/bin/env python3
"""GameNight Guide static site builder.
Data: ESPN public site API (no key). Builds ./site and ./email."""
import json, os, shutil, html, gzip, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "site")
EMAIL = os.path.join(ROOT, "email")
CFG = json.load(open(os.path.join(ROOT, "config.json")))
ET, PT = ZoneInfo("America/New_York"), ZoneInfo("America/Los_Angeles")
API = "https://site.api.espn.com/apis/site/v2/sports/{path}/{ep}"
LEAGUES = {"nfl": "football/nfl", "nba": "basketball/nba"}
e = html.escape
BASE = os.environ.get("BASE_PATH", "").rstrip("/")  # e.g. /gamenight-guide on GitHub Pages

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GameNightGuide/0.1", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    return json.loads(b)

# ---------- where-to-watch knowledge (no prices: none verified) ----------
SVC = CFG["affiliate_links"]
def link(key):
    s = SVC[key]; url = s.get("affiliate_url") or s["home"]
    placeholder = isinstance(url, str) and url.startswith("PLACEHOLDER")
    href = s["home"] if placeholder else url
    slot = f' data-affiliate-slot="{key}"' if placeholder else ""
    return f'<a href="{e(href)}" rel="sponsored noopener" target="_blank"{slot}>{e(s["label"])}</a>'

# network -> (kind, note, [service keys])
NETWORKS = {
    "CBS":  ("Broadcast", "Free with an antenna. Streaming: Paramount+ or a live-TV service.", ["antenna","paramount","youtubetv","fubo","hululive"]),
    "FOX":  ("Broadcast", "Free with an antenna. Streaming: FOX One or a live-TV service.", ["antenna","foxone","youtubetv","fubo","hululive","sling"]),
    "NBC":  ("Broadcast", "Free with an antenna. Streaming: Peacock or a live-TV service.", ["antenna","peacock","youtubetv","fubo","hululive","sling"]),
    "ABC":  ("Broadcast", "Free with an antenna. Streaming: the ESPN app or a live-TV service.", ["antenna","espn","youtubetv","fubo","hululive"]),
    "ESPN": ("Cable/streaming", "Cheapest standalone: the ESPN app (the tier that includes ESPN's TV channels). Also on most live-TV services.", ["espn","youtubetv","fubo","hululive","sling"]),
    "ESPN2":("Cable/streaming", "Same as ESPN: the ESPN app or a live-TV service.", ["espn","youtubetv","fubo","hululive","sling"]),
    "PRIME VIDEO": ("Streaming", "Included with Amazon Prime (or Prime Video on its own). For NFL, local stations in the two teams' markets also air it.", ["prime"]),
    "NETFLIX": ("Streaming", "Included with any Netflix plan.", ["netflix"]),
    "PEACOCK": ("Streaming", "Peacock subscription.", ["peacock"]),
    "NBCSN": ("Cable/streaming", "NBC's sports channel. These games also stream on Peacock.", ["peacock"]),
    "NBA TV": ("Cable/streaming", "Included with NBA League Pass; also on some live-TV packages.", ["leaguepass","youtubetv","sling"]),
    "NFL NETWORK": ("Cable/streaming", "On most live-TV services.", ["youtubetv","fubo","sling","hululive"]),
    "NBA LEAGUE PASS": ("Streaming", "Out-of-market games only. Blacked out for your local team and for national TV games.", ["leaguepass"]),
}
ALIASES = {"FOX":"FOX","FOX SPORTS":"FOX","ESPN UNLIMITED":"ESPN","ESPN+":"ESPN","ABC/ESPN":"ABC","PRIME":"PRIME VIDEO","AMAZON PRIME VIDEO":"PRIME VIDEO","NFL NET":"NFL NETWORK","NFLN":"NFL NETWORK"}
def norm(name): u = name.strip().upper(); return ALIASES.get(u, u)

REGIONAL_NOTE_NBA = "Local regional channel / team app. Usually only for viewers in the team's home market. Outside it, use NBA League Pass."
def regional_services(name):
    return ["dazn"] if "DAZN" in name.upper() else []

# ---------- fetch ----------
def fetch(now):
    teams, games = {}, []
    for lg, path in LEAGUES.items():
        for t in get(API.format(path=path, ep="teams"))["sports"][0]["leagues"][0]["teams"]:
            t = t["team"]
            teams[(lg, t["id"])] = dict(lg=lg, id=t["id"], abbr=t["abbreviation"], name=t["displayName"],
                short=t.get("shortDisplayName", t["name"]), slug=t["slug"], color="#"+t.get("color","333333"),
                alt="#"+t.get("alternateColor","ffffff"), logo=(t.get("logos") or [{}])[0].get("href",""))
        day = now.astimezone(ET).date()
        seen = set()
        for i in range(8):
            d = (day + timedelta(days=i)).strftime("%Y%m%d")
            for ev in get(API.format(path=path, ep=f"scoreboard?dates={d}&limit=200")).get("events", []):
                if ev["id"] in seen: continue
                seen.add(ev["id"])
                c = ev["competitions"][0]
                start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                state = ev["status"]["type"]["state"]
                if state == "post" or start > now + timedelta(days=7): continue
                home = next(x for x in c["competitors"] if x["homeAway"] == "home")
                away = next(x for x in c["competitors"] if x["homeAway"] == "away")
                nat, reg = [], {"home": [], "away": []}
                geo = c.get("geoBroadcasts") or []
                if geo:
                    for g in geo:
                        n = g["media"]["shortName"]; m = g["market"]["type"].lower()
                        (nat if m == "national" else reg.setdefault(m, [])).append(n)
                else:
                    for b in c.get("broadcasts", []):
                        for n in b.get("names", []):
                            (nat if norm(n) in NETWORKS else reg["home"]).append(n)
                nat = list(dict.fromkeys(nat))
                if lg == "nba" and not any(norm(n) == "NBA LEAGUE PASS" for n in nat):
                    # League Pass carries every non-national game out of market
                    if not any(norm(n) in NETWORKS and norm(n) != "NBA LEAGUE PASS" for n in nat):
                        nat.append("NBA League Pass")
                # NFL Sunday-afternoon CBS/FOX games are regional, not truly national
                sunday_pm = lg == "nfl" and start.astimezone(ET).weekday() == 6 and start.astimezone(ET).hour < 19
                is_regional_nfl = sunday_pm and all(norm(n) in ("CBS", "FOX") for n in nat)
                games.append(dict(id=ev["id"], lg=lg, start=start, state=state, name=ev["shortName"],
                    status=ev["status"]["type"]["shortDetail"],
                    home=teams.get((lg, home["team"]["id"])), away=teams.get((lg, away["team"]["id"])),
                    nat=nat, reg=reg, regional_nfl=is_regional_nfl,
                    national_tv=any(norm(n) not in ("NBA LEAGUE PASS",) for n in nat) and not is_regional_nfl))
    games.sort(key=lambda g: g["start"])
    return teams, games

# ---------- render helpers ----------
def fmt_time(dt):
    et, pt = dt.astimezone(ET), dt.astimezone(PT)
    return et.strftime("%a %b %-d"), f'{et.strftime("%-I:%M %p")} ET / {pt.strftime("%-I:%M %p")} PT'

def tag(n, cls="net"): return f'<span class="{cls}">{e(n)}</span>'

def watch_notes(g, team=None):
    """Return HTML list explaining the cheapest ways to watch."""
    items, done = [], set()
    for n in g["nat"]:
        k = norm(n)
        if k in done: continue
        done.add(k)
        if g["regional_nfl"] and k in ("CBS", "FOX"):
            items.append(f'<li><b>{e(n)}</b> (regional): shown on your local {e(n)} station in some markets. Free with {link("antenna")}. '
                         f'Out of market, it\'s on {link("sundayticket")}.</li>')
            continue
        if k in NETWORKS:
            kind, note, svcs = NETWORKS[k]
            items.append(f'<li><b>{e(n)}</b> <small>{kind}</small>: {e(note)} <span class="svcs">{" · ".join(link(s) for s in svcs)}</span></li>')
        else:
            items.append(f'<li><b>{e(n)}</b>: check the network\'s app or your TV provider.</li>')
    if g["lg"] == "nba":
        sides = [("home", g["home"]), ("away", g["away"])]
        if team: sides = [s for s in sides if s[1] and s[1]["id"] == team["id"]] + [s for s in sides if not (s[1] and s[1]["id"] == team["id"])]
        for side, t in sides:
            nets = list(dict.fromkeys(g["reg"].get(side, [])))
            if not nets or not t: continue
            svc = sorted({s for n in nets for s in regional_services(n)})
            extra = (" Streaming: " + " · ".join(link(s) for s in svc)) if svc else ""
            items.append(f'<li><b>{e(t["short"])} local:</b> {", ".join(tag(n, "net reg") for n in nets)}. {e(REGIONAL_NOTE_NBA)}{extra}</li>')
    return "<ul class=\"watch\">" + "".join(items) + "</ul>"

def team_url(t): return f'{BASE}/{t["lg"]}/{t["slug"]}/'

def game_card(g, team=None):
    day, tm = fmt_time(g["start"])
    a, h = g["away"], g["home"]
    def tlink(t): return f'<a href="{team_url(t)}">{e(t["name"])}</a>' if t else "TBD"
    if team:
        opp = h if a and a["id"] == team["id"] else a
        title = f'{"@" if opp is h else "vs"} {tlink(opp)}'
    else:
        title = f'{tlink(a)} <span class="at">@</span> {tlink(h)}'
    live = '<span class="live">LIVE</span> ' if g["state"] == "in" else ""
    nets = " ".join(tag(n) for n in g["nat"]) or '<span class="net">TBD</span>'
    if g["regional_nfl"]: nets += ' <span class="pill">regional</span>'
    if team and g["lg"] == "nba":
        side = "home" if h and h["id"] == team["id"] else "away"
        loc = list(dict.fromkeys(g["reg"].get(side, [])))
        if loc: nets += ' <span class="pill">local</span> ' + " ".join(tag(n, "net reg") for n in loc)
    return f'''<article class="game {g["lg"]}">
  <div class="when"><span class="lg">{g["lg"].upper()}</span> {live}<b>{day}</b> · {tm}</div>
  <h3>{title}</h3>
  <div class="nets">{nets}</div>
  <details><summary>Cheapest way to watch</summary>{watch_notes(g, team)}</details>
</article>'''

CSS = """
:root{--bg:#0b1220;--card:#131c2e;--ink:#eef2f8;--mute:#9aa7bd;--acc:#ff5a1f;--acc2:#1fb6ff;--line:#22304a}
*{box-sizing:border-box}body{margin:0;font:16px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--acc2);text-decoration:none}a:hover{text-decoration:underline}
header.top{background:linear-gradient(90deg,#0b1220,#17223a);border-bottom:3px solid var(--acc);padding:14px 16px}
header.top .wrap{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.brand{font-weight:900;font-size:22px;letter-spacing:.5px;color:var(--ink)}.brand span{color:var(--acc)}
nav a{color:var(--mute);margin-right:14px;font-weight:600}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
h1{font-size:28px;margin:22px 0 4px}h2{font-size:20px;margin:28px 0 10px;border-left:4px solid var(--acc);padding-left:10px}
.sub{color:var(--mute);margin:0 0 14px}
.game{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}
.game h3{margin:4px 0 8px;font-size:18px}.game h3 a{color:var(--ink)}.at{color:var(--mute)}
.when{color:var(--mute);font-size:14px}.when b{color:var(--ink)}
.lg{display:inline-block;font-size:11px;font-weight:800;padding:2px 6px;border-radius:4px;background:#2b3a59;margin-right:4px}
.nfl .lg{background:#013369}.nba .lg{background:#c9082a}
.net{display:inline-block;background:#fff;color:#111;font-weight:800;font-size:13px;padding:3px 8px;border-radius:6px;margin:2px 4px 2px 0}
.net.reg{background:#2b3a59;color:#dfe7f5;font-weight:600}
.pill{font-size:12px;color:var(--mute);border:1px solid var(--line);border-radius:10px;padding:1px 8px}
.live{color:#fff;background:#e11d48;font-size:11px;font-weight:800;padding:2px 6px;border-radius:4px}
details{margin-top:8px}summary{cursor:pointer;color:var(--acc);font-weight:700;font-size:14px}
ul.watch{margin:8px 0 0;padding-left:18px;font-size:14px;color:#d5dceb}ul.watch li{margin:6px 0}ul.watch small{color:var(--mute)}
.svcs{display:block;font-size:13px}
.teams{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.teams a{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;color:var(--ink);font-size:14px}
.teams img{width:28px;height:28px}
.hero{display:flex;align-items:center;gap:14px;margin-top:20px;padding:16px;border-radius:14px}
.hero h1,.hero div{text-shadow:0 1px 3px rgba(0,0,0,.8)}.hero img{width:72px;height:72px;background:#fff;border-radius:50%;padding:6px}.hero h1{margin:0}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:12px;padding:16px;color:var(--mute)}
form.signup{background:#1a2540;border:1px solid var(--line);border-radius:12px;padding:14px;margin:24px 0}
form.signup h3{margin:0 0 6px}form.signup p{margin:0 0 10px;color:var(--mute);font-size:14px}
form.signup .row{display:flex;gap:8px;flex-wrap:wrap}
form.signup input[type=email]{flex:1;min-width:200px;padding:10px;border-radius:8px;border:1px solid var(--line);background:#0e1626;color:var(--ink);font-size:16px}
form.signup button{padding:10px 16px;border:0;border-radius:8px;background:var(--acc);color:#fff;font-weight:800;font-size:16px;cursor:pointer}
footer{color:var(--mute);font-size:13px;border-top:1px solid var(--line);margin-top:30px;padding:16px 0 40px}
.filters a{display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--line);border-radius:14px;color:var(--ink);font-size:14px}
"""

def page(title, body, desc="Which channel or app every NFL and NBA game is on this week, plus the cheapest way to watch."):
    built = datetime.now(PT).strftime("%a %b %-d, %-I:%M %p PT")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="stylesheet" href="{BASE}/style.css"></head><body>
<header class="top"><div class="wrap"><a class="brand" href="{BASE}/">GameNight<span>Guide</span></a>
<nav><a href="{BASE}/">This week</a><a href="{BASE}/nfl/">NFL teams</a><a href="{BASE}/nba/">NBA teams</a></nav></div></header>
<main class="wrap">{body}</main>
<footer class="wrap">Schedules and channels refresh automatically from public league data. Last updated {built}. Channels can change; check before game time.
Some links may be affiliate links, and we may earn a commission at no cost to you. Not affiliated with the NFL or NBA.</footer>
</body></html>'''

def signup(team=None):
    who = team["name"] if team else "your teams"
    hidden = f'<input type="hidden" name="team" value="{e(team["lg"]+":"+team["abbr"])}">' if team else ""
    return f'''<form class="signup" method="post" action="{e(CFG["newsletter_endpoint"])}" data-placeholder-endpoint="true" onsubmit="if(this.action.indexOf('PLACEHOLDER')>-1){{alert('Signup is not live yet.');return false}}">
<h3>Monday email: {e(who)}</h3><p>Every Monday: this week's games, the channels they're on, and the cheapest way to watch. Free.</p>
{hidden}<div class="row"><input type="email" name="email" required placeholder="you@email.com" aria-label="Email"><button type="submit">Sign me up</button></div></form>'''

def write(path, s):
    full = os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w").write(s)

def build():
    now = datetime.now(timezone.utc)
    teams, games = fetch(now)
    if os.path.exists(OUT): shutil.rmtree(OUT)
    os.makedirs(OUT)
    open(os.path.join(OUT, "style.css"), "w").write(CSS)
    json.dump([{**{k: v for k, v in g.items() if k not in ("home", "away", "start")},
                "start": g["start"].isoformat(), "home": g["home"]["abbr"] if g["home"] else None,
                "away": g["away"]["abbr"] if g["away"] else None} for g in games],
              open(os.path.join(OUT, "games.json"), "w"), indent=1)
    natl = [g for g in games if g["national_tv"]]
    # home
    body = '<h1>Where to watch this week</h1><p class="sub">Every national TV NFL and NBA game in the next 7 days, with times in ET and PT and the cheapest way to watch.</p>'
    for lg, label in (("nfl", "NFL"), ("nba", "NBA")):
        gs = [g for g in natl if g["lg"] == lg]
        body += f'<h2>{label} national games</h2>' + ("".join(game_card(g) for g in gs) or '<div class="empty">No national games in the next 7 days.</div>')
    reg = [g for g in games if g["lg"] == "nfl" and g["regional_nfl"]]
    if reg:
        body += '<h2>NFL Sunday regional games (CBS / FOX)</h2><p class="sub">Which of these you get depends on where you live. Out of market, they\'re on NFL Sunday Ticket.</p>' + "".join(game_card(g) for g in reg)
    body += f'<h2>Find your team</h2><div class="filters"><a href="{BASE}/nfl/">All 32 NFL teams →</a><a href="{BASE}/nba/">All 30 NBA teams →</a></div>' + signup()
    write("index.html", page("GameNight Guide: Where to watch NFL & NBA this week", body))
    # league indexes + team pages
    byes = {"nfl": [], "nba": []}
    for lg, label in (("nfl", "NFL"), ("nba", "NBA")):
        lt = sorted([t for t in teams.values() if t["lg"] == lg], key=lambda t: t["name"])
        grid = "".join(f'<a href="{team_url(t)}"><img src="{e(t["logo"])}" alt="" loading="lazy">{e(t["name"])}</a>' for t in lt)
        write(f"{lg}/index.html", page(f"{label} teams: where to watch | GameNight Guide",
              f'<h1>{label} teams</h1><p class="sub">Pick your team to see this week\'s games and where to watch them.</p><div class="teams">{grid}</div>'))
        for t in lt:
            tg = [g for g in games if g["lg"] == lg and t["id"] in ((g["home"] or {}).get("id"), (g["away"] or {}).get("id"))]
            if tg:
                inner = "".join(game_card(g, t) for g in tg)
            else:
                byes[lg].append(t["abbr"])
                msg = "It's a bye week. No game in the next 7 days." if lg == "nfl" else "No games scheduled in the next 7 days."
                inner = f'<div class="empty">{msg} Sign up below and we\'ll send you the next one on Monday.</div>'
            hero = f'<div class="hero" style="background:linear-gradient(90deg,{t["color"]},#131c2e)"><img src="{e(t["logo"])}" alt="{e(t["name"])} logo"><div><h1>{e(t["name"])}</h1><div>Where to watch: next 7 days</div></div></div>'
            write(f"{lg}/{t['slug']}/index.html", page(f"How to watch the {t['name']} this week | GameNight Guide",
                  hero + "<h2>Upcoming games</h2>" + inner + signup(t),
                  f"What channel the {t['name']} game is on this week, with ET/PT times and the cheapest way to stream it."))
    build_email(natl, now)
    report = dict(built_at=datetime.now(PT).isoformat(), games=len(games), national=len(natl),
                  teams=len(teams), no_games=byes)
    json.dump(report, open(os.path.join(OUT, "build-report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))

def build_email(natl, now):
    os.makedirs(EMAIL, exist_ok=True)
    wk = now.astimezone(PT)
    title = f"GameNight Guide: week of {wk.strftime('%b %-d')}"
    md = [f"# {title}", "", "Here's every national TV NFL and NBA game this week and where to watch it. Times in ET / PT.", ""]
    htm = [f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#111"><h1 style="border-bottom:3px solid #ff5a1f">{e(title)}</h1><p>Here\'s every national TV NFL and NBA game this week and where to watch it. Times in ET / PT.</p>']
    for lg, label in (("nfl", "🏈 NFL"), ("nba", "🏀 NBA")):
        gs = [g for g in natl if g["lg"] == lg]
        md += [f"## {label}", ""]; htm.append(f"<h2>{label}</h2><table style='width:100%;border-collapse:collapse;font-size:14px'>")
        for g in gs:
            day, tm = fmt_time(g["start"])
            nets = ", ".join(g["nat"])
            md.append(f"- **{g['away']['name']} @ {g['home']['name']}**: {day}, {tm}, on **{nets}**")
            htm.append(f"<tr><td style='padding:6px;border-bottom:1px solid #eee'><b>{e(g['away']['name'])} @ {e(g['home']['name'])}</b><br>{day} · {tm}</td><td style='padding:6px;border-bottom:1px solid #eee;text-align:right'><b>{e(nets)}</b></td></tr>")
        if not gs: md.append("- No national games this week.")
        md.append(""); htm.append("</table>")
    tip = ("**Cheapest-way tip:** CBS, FOX, NBC and ABC games are free with an HD antenna. Thursday NFL is on Prime Video. "
           "Prime Video and Peacock games stream only on those apps. ESPN games need the ESPN app or a live-TV service.")
    md += [tip, "", "Want just your team? Find it at GameNight Guide and sign up for its Monday email.", "",
           "_Some links may be affiliate links. Channels can change. Check before game time._"]
    htm.append(f"<p>{tip.replace('**Cheapest-way tip:**','<b>Cheapest-way tip:</b>')}</p><p>Want just your team? Find it at GameNight Guide and sign up for its Monday email.</p><p style='color:#888;font-size:12px'>Some links may be affiliate links. Channels can change. Check before game time.</p></div>")
    open(os.path.join(EMAIL, "monday-email.md"), "w").write("\n".join(md))
    open(os.path.join(EMAIL, "monday-email.html"), "w").write("\n".join(htm))

if __name__ == "__main__":
    build()
