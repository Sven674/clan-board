#!/usr/bin/env python3
"""Holt Clan-Daten über die Clash-of-Clans-API (via RoyaleAPI-Proxy),
speichert den Verlauf in data/ und erzeugt data/board.json für die Webseite.

Token: Umgebungsvariable COC_API_TOKEN oder Datei in COC_API_TOKEN_FILE.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CONFIG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
BASE = CONFIG.get("api_base", "https://cocproxy.royaleapi.dev/v1")

# Werte aus dem Spielerprofil, deren Änderung eine eigene Aktion des Spielers bedeutet
ACTIVE_ACHIEVEMENTS = {
    "Gold Grab", "Elixir Escapade", "Heroic Heist", "Games Champion",
    "Well Seasoned", "Friend in Need", "Sharing is caring", "Siege Sharer",
    "Aggressive Capitalism", "Most Valuable Clanmate", "War League Legend",
    "Conqueror", "Unbreakable",
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_coc_time(s):
    # Format der API: 20261103T120000.000Z
    return datetime.strptime(s, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)


def load_token():
    tok = os.environ.get("COC_API_TOKEN", "").strip()
    if not tok and os.environ.get("COC_API_TOKEN_FILE"):
        with open(os.path.expanduser(os.environ["COC_API_TOKEN_FILE"]), encoding="utf-8") as f:
            tok = f.read().strip()
    if not tok:
        sys.exit("Kein API-Token gefunden (COC_API_TOKEN oder COC_API_TOKEN_FILE).")
    return tok


TOKEN = None


class Voruebergehend(Exception):
    """API oder Proxy kurz nicht erreichbar (Wartung, Überlastung, Verbindungsfehler)."""


def api(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                # 403 = Kriegsprotokoll privat oder Schlüssel/IP falsch, 404 = nicht vorhanden
                return {"_error": e.code, "_reason": e.read().decode("utf-8", "replace")[:200]}
            # 429 = zu viele Anfragen, 5xx = Wartung (503) oder Proxy-/Cloudflare-Fehler (520-530)
            if e.code == 429 or e.code >= 500:
                if attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise Voruebergehend("HTTP %s bei %s" % (e.code, path))
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise Voruebergehend("Verbindung fehlgeschlagen bei %s: %s" % (path, e))


def enc(tag):
    return urllib.parse.quote(tag)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, obj, pretty=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def safe(tag):
    return tag.replace("#", "")


# ---------------------------------------------------------------- Kriege

def compact_war(war, clan_tag, kind, war_tag=None):
    if war.get("clan", {}).get("tag") == clan_tag:
        us, them = war["clan"], war["opponent"]
    else:
        us, them = war["opponent"], war["clan"]
    opp_th = {m["tag"]: m.get("townhallLevel") for m in them.get("members", [])}
    opp_pos = {m["tag"]: m.get("mapPosition") for m in them.get("members", [])}
    # Verteidigungen: Angriffe des Gegners auf unsere Spieler
    defenses = {}
    for om in them.get("members", []):
        for a in om.get("attacks", []) or []:
            defenses.setdefault(a.get("defenderTag"), []).append({
                "stars": a.get("stars", 0), "pct": a.get("destructionPercentage", 0),
                "attTh": om.get("townhallLevel"),
            })
    members = []
    for m in us.get("members", []):
        attacks = []
        for a in m.get("attacks", []) or []:
            attacks.append({
                "stars": a.get("stars", 0),
                "pct": a.get("destructionPercentage", 0),
                "defTh": opp_th.get(a.get("defenderTag")),
                "defPos": opp_pos.get(a.get("defenderTag")),
                "order": a.get("order"),
            })
        members.append({
            "tag": m["tag"], "name": m.get("name"), "th": m.get("townhallLevel"),
            "pos": m.get("mapPosition"), "attacks": attacks,
            "defenses": defenses.get(m["tag"], []),
        })
    rec = {
        "kind": kind,
        "warTag": war_tag,
        "state": war.get("state"),
        "teamSize": war.get("teamSize"),
        "attacksPerMember": war.get("attacksPerMember", 1 if kind == "cwl" else 2),
        "preparationStartTime": war.get("preparationStartTime"),
        "startTime": war.get("startTime"),
        "endTime": war.get("endTime"),
        "us": {"stars": us.get("stars", 0), "pct": us.get("destructionPercentage", 0),
               "attacks": us.get("attacks", 0)},
        "opponent": {"name": them.get("name"), "tag": them.get("tag"),
                     "stars": them.get("stars", 0), "pct": them.get("destructionPercentage", 0),
                     "badge": (them.get("badgeUrls") or {}).get("small")},
        "members": members,
    }
    return rec


def store_war(rec, clan_tag, fetched_at):
    if not rec.get("preparationStartTime"):
        return
    key = "%s_%s_%s" % (safe(clan_tag), rec["kind"], rec["preparationStartTime"][:15])
    path = os.path.join(DATA, "wars", key + ".json")
    old = read_json(path, None)
    rec["lastSeen"] = iso(fetched_at)
    rec["final"] = rec["state"] == "warEnded"
    if old and old.get("final") and not rec["final"]:
        return  # nie einen fertigen Krieg mit einem älteren Stand überschreiben
    write_json(path, rec, pretty=True)


def fetch_wars(clan_tag, fetched_at):
    cur = api("/clans/%s/currentwar" % enc(clan_tag))
    current = None
    if cur and "_error" not in cur and cur.get("state") not in (None, "notInWar"):
        current = compact_war(cur, clan_tag, "regular")
        store_war(current, clan_tag, fetched_at)

    group = api("/clans/%s/currentwar/leaguegroup" % enc(clan_tag))
    cwl_current = None
    table = {}
    if group and "_error" not in group and group.get("rounds"):
        for c in group.get("clans", []):
            table[c["tag"]] = {"tag": c["tag"], "name": c.get("name"), "stars": 0, "pct": 0.0,
                               "wins": 0, "losses": 0, "ties": 0}
        for rnd in group["rounds"]:
            for wt in rnd.get("warTags", []):
                if not wt or wt == "#0":
                    continue
                w = api("/clanwarleagues/wars/%s" % enc(wt))
                if not w or "_error" in w:
                    continue
                cwl_table_add(table, w)
                if clan_tag not in (w.get("clan", {}).get("tag"), w.get("opponent", {}).get("tag")):
                    continue
                rec = compact_war(w, clan_tag, "cwl", wt)
                store_war(rec, clan_tag, fetched_at)
                if rec["state"] in ("inWar", "preparation"):
                    if cwl_current is None or rec["state"] == "inWar":
                        cwl_current = rec
    return current, cwl_current, (group if group and "_error" not in group else None), cwl_table(table)


def cwl_table_add(table, w):
    """Ligatabelle: Sterne (+10 je Sieg nach Kriegsende), danach Zerstörung, wie im Spiel."""
    st = w.get("state")
    if st not in ("inWar", "warEnded"):
        return
    a, b = w.get("clan", {}), w.get("opponent", {})
    for x, y in ((a, b), (b, a)):
        t = table.get(x.get("tag"))
        if not t:
            continue
        t["stars"] += x.get("stars", 0)
        t["pct"] += x.get("destructionPercentage", 0)
        if st == "warEnded":
            me = (x.get("stars", 0), x.get("destructionPercentage", 0))
            them = (y.get("stars", 0), y.get("destructionPercentage", 0))
            if me > them:
                t["wins"] += 1
                t["stars"] += 10
            elif me < them:
                t["losses"] += 1
            else:
                t["ties"] += 1


def cwl_table(table):
    rows = sorted(table.values(), key=lambda t: (-t["stars"], -t["pct"]))
    for i, t in enumerate(rows, 1):
        t["rank"] = i
        t["pct"] = round(t["pct"], 1)
    return rows


# ---------------------------------------------------------------- Clanstadt

def fetch_raids(clan_tag):
    res = api("/clans/%s/capitalraidseasons?limit=10" % enc(clan_tag))
    if not res or "_error" in res:
        return
    for season in res.get("items", []):
        rec = {
            "startTime": season.get("startTime"),
            "endTime": season.get("endTime"),
            "state": season.get("state"),
            "capitalTotalLoot": season.get("capitalTotalLoot"),
            "raidsCompleted": season.get("raidsCompleted"),
            "totalAttacks": season.get("totalAttacks"),
            "offensiveReward": season.get("offensiveReward"),
            "defensiveReward": season.get("defensiveReward"),
            "members": [{
                "tag": m["tag"], "name": m.get("name"),
                "attacks": m.get("attacks", 0),
                "limit": m.get("attackLimit", 5) + m.get("bonusAttackLimit", 0),
                "loot": m.get("capitalResourcesLooted", 0),
            } for m in season.get("members", []) or []],
        }
        key = "%s_%s" % (safe(clan_tag), (season.get("startTime") or "x")[:15])
        path = os.path.join(DATA, "raids", key + ".json")
        # Die API liefert die Spielerliste nur fürs letzte Wochenende:
        # eine gespeicherte Liste nie durch eine leere ersetzen
        old = read_json(path, None)
        if not rec["members"] and old and old.get("members"):
            rec["members"] = old["members"]
        write_json(path, rec, pretty=True)


# ---------------------------------------------------------------- Mitglieder

def activity_signature(p, member):
    ach = {a["name"]: a.get("value", 0) for a in p.get("achievements", [])}
    levels = sum(x.get("level", 0) for k in ("troops", "heroes", "spells", "heroEquipment")
                 for x in p.get(k, []) or [])
    return [
        member.get("donations", 0), member.get("donationsReceived", 0),
        p.get("attackWins", 0), p.get("expLevel", 0), p.get("warStars", 0),
        p.get("clanCapitalContributions", 0), p.get("builderBaseTrophies", 0),
        p.get("townHallLevel", 0), p.get("name"), levels,
        sum(v for k, v in ach.items() if k in ACTIVE_ACHIEVEMENTS),
    ]


def clan_games_window(dt):
    """Clanspiele laufen vom 22. 08:00 UTC bis 28. 08:00 UTC."""
    start = dt.replace(day=22, hour=8, minute=0, second=0, microsecond=0)
    end = dt.replace(day=28, hour=8, minute=0, second=0, microsecond=0)
    return start, end


def update_members(clan, state, fetched_at):
    tag = clan["tag"]
    cs = state.setdefault("clans", {}).setdefault(tag, {})
    tracked = cs.setdefault("members", {})
    log = cs.setdefault("log", [])
    now = iso(fetched_at)
    current_tags = set()
    gs_start, gs_end = clan_games_window(fetched_at)
    gs_key = fetched_at.strftime("%Y-%m")
    in_games = gs_start <= fetched_at < gs_end + timedelta(hours=6)

    for m in clan.get("memberList", []):
        mt = m["tag"]
        current_tags.add(mt)
        t = tracked.get(mt)
        if t is None or not t.get("inClan"):
            log.append({"time": now, "type": "join", "tag": mt, "name": m.get("name"),
                        "th": m.get("townHallLevel")})
            if t is None:
                t = tracked[mt] = {"firstSeen": now, "joins": 0}
            t["joins"] = t.get("joins", 0) + 1
            t["joinedAt"] = now
            t["inClan"] = True
        p = api("/players/%s" % enc(mt))
        if p and "_error" not in p:
            sig = activity_signature(p, m)
            if t.get("sig") != sig:
                if t.get("sig") is not None:
                    t["lastActive"] = now
                t["sig"] = sig
            t.setdefault("lastActive", None)
            ach = {a["name"]: a.get("value", 0) for a in p.get("achievements", [])}
            games_total = ach.get("Games Champion", 0)
            heroes = {h["name"]: h.get("level") for h in p.get("heroes", []) or []
                      if h.get("village") == "home"}
            t["profile"] = {
                "warStars": p.get("warStars", 0), "attackWins": p.get("attackWins", 0),
                "defenseWins": p.get("defenseWins", 0), "bestTrophies": p.get("bestTrophies"),
                "capitalContrib": p.get("clanCapitalContributions", 0),
                "warPreference": p.get("warPreference"), "heroes": heroes,
                "legend": (p.get("legendStatistics") or {}).get("legendTrophies"),
                "builderTrophies": p.get("builderBaseTrophies"),
                "gamesTotal": games_total,
                "boosts": [x["name"] for x in p.get("troops", []) or []
                           if x.get("superTroopIsActive")],
            }
            # Hauptstadtgold je Raid-Woche (Freitag 07:00 UTC bis Freitag)
            wk_start = (fetched_at - timedelta(days=(fetched_at.weekday() - 4) % 7)).replace(
                hour=7, minute=0, second=0, microsecond=0)
            if fetched_at < wk_start:
                wk_start -= timedelta(days=7)
            cap = t.setdefault("capital", {})
            ck = wk_start.strftime("%Y-%m-%d")
            cw = cap.setdefault(ck, {"base": p.get("clanCapitalContributions", 0)})
            cw["gold"] = p.get("clanCapitalContributions", 0) - cw["base"]
            for k in sorted(cap)[:-6]:
                del cap[k]
            # Clanspiele: Startwert beim ersten Abruf im Zeitfenster merken
            games = t.setdefault("games", {})
            if in_games:
                g = games.setdefault(gs_key, {"base": games_total})
                g["points"] = games_total - g["base"]
            # alte Monate begrenzen
            for k in sorted(games)[:-6]:
                del games[k]
        # Spenden je Saison: sinkt der Wert, hat eine neue Saison begonnen
        don = t.setdefault("donations", {"season": [], "cur": None})
        cur = {"d": m.get("donations", 0), "r": m.get("donationsReceived", 0), "since": now}
        prev = don.get("cur")
        if prev and (cur["d"] < prev["d"] or cur["r"] < prev["r"]):
            don["season"].append({"end": now, "d": prev["d"], "r": prev["r"]})
            don["season"] = don["season"][-6:]
            cur["since"] = now
        elif prev:
            cur["since"] = prev.get("since", now)
        don["cur"] = cur
        # Änderungen protokollieren (wie im ClashPerk-Log)
        changes = [
            ("role", t.get("role"), m.get("role")),
            ("name", t.get("name"), m.get("name")),
            ("th", t.get("th"), m.get("townHallLevel")),
        ]
        if p and "_error" not in p:
            changes.append(("warPref", t.get("warPref"), p.get("warPreference")))
            t["warPref"] = p.get("warPreference")
        for typ, old, new in changes:
            if old is not None and new is not None and old != new:
                log.append({"time": now, "type": typ, "tag": mt, "name": m.get("name"),
                            "th": m.get("townHallLevel"), "from": old, "to": new})
        t.update({
            "name": m.get("name"), "role": m.get("role"), "th": m.get("townHallLevel"),
            "exp": m.get("expLevel"), "trophies": m.get("trophies"),
            "league": (m.get("league") or {}).get("name"),
            "leagueIcon": ((m.get("league") or {}).get("iconUrls") or {}).get("small"),
            "builderTrophies": m.get("builderBaseTrophies"), "lastSeen": now,
        })

    for mt, t in tracked.items():
        if t.get("inClan") and mt not in current_tags:
            t["inClan"] = False
            t["leftAt"] = now
            log.append({"time": now, "type": "leave", "tag": mt, "name": t.get("name"),
                        "th": t.get("th")})
    cs["log"] = log[-300:]


# ---------------------------------------------------------------- Auswertung

def load_records(folder, clan_tag):
    out = []
    pre = safe(clan_tag) + "_"
    d = os.path.join(DATA, folder)
    for fn in sorted(os.listdir(d)):
        if fn.startswith(pre) and fn.endswith(".json"):
            out.append(read_json(os.path.join(d, fn), None))
    return [r for r in out if r]


def war_member_stats(wars, recent_n):
    """Pro Spieler: Angriffe, verpasste Angriffe, Sterne, 3-Sterne-Quote."""
    stats = {}
    finished = sorted([w for w in wars if w.get("final")],
                      key=lambda w: w["preparationStartTime"])
    recent = set(id(w) for w in finished[-recent_n:])
    for w in finished:
        apm = w.get("attacksPerMember") or 2
        for m in w["members"]:
            s = stats.setdefault(m["tag"], {
                "wars": 0, "attacks": 0, "missed": 0, "stars": 0, "triples": 0,
                "pct": 0.0, "recentMissed": 0, "recentWars": 0, "possible": 0,
                "cwlWars": 0, "cwlStars": 0, "cwlMissed": 0, "sameThTriples": 0,
                "sameThAttacks": 0, "lastMissed": None,
                "defs": 0, "defStars": 0, "defTriples": 0,
            })
            for dfn in m.get("defenses", []):
                s["defs"] += 1
                s["defStars"] += dfn["stars"]
                if dfn["stars"] == 3:
                    s["defTriples"] += 1
            used = len(m["attacks"])
            missed = max(0, apm - used)
            s["wars"] += 1
            s["possible"] += apm
            s["attacks"] += used
            s["missed"] += missed
            if missed:
                s["lastMissed"] = w["endTime"]
            if id(w) in recent:
                s["recentWars"] += 1
                s["recentMissed"] += missed
            if w["kind"] == "cwl":
                s["cwlWars"] += 1
                s["cwlMissed"] += missed
            for a in m["attacks"]:
                s["stars"] += a["stars"]
                s["pct"] += a["pct"]
                if a["stars"] == 3:
                    s["triples"] += 1
                if a.get("defTh") and a["defTh"] == m.get("th"):
                    s["sameThAttacks"] += 1
                    if a["stars"] == 3:
                        s["sameThTriples"] += 1
                if w["kind"] == "cwl":
                    s["cwlStars"] += a["stars"]
    return stats


def latest_capital_gold(t):
    cap = t.get("capital") or {}
    return cap[max(cap)].get("gold") if cap else None


def with_standings(s, st):
    if s and st and st.get("season", "")[:7] == s["season"]:
        s["standings"] = st["table"]
    return s


def cwl_season(wars, roster=None, back=0):
    """Auswertung einer Ligasaison: Tage und Spieler. back=0 neueste, back=1 die davor."""
    cwl = [w for w in wars if w.get("kind") == "cwl" and w.get("preparationStartTime")]
    seasons = sorted({w["preparationStartTime"][:6] for w in cwl}, reverse=True)
    if len(seasons) <= back:
        return None
    season = seasons[back]
    days = sorted([w for w in cwl if w["preparationStartTime"][:6] == season],
                  key=lambda w: w["preparationStartTime"])
    players = {}
    rounds = []
    for i, w in enumerate(days, 1):
        a, b = w["us"], w["opponent"]
        res = "offen"
        if w.get("final"):
            res = "sieg" if (a["stars"], a["pct"]) > (b["stars"], b["pct"]) else (
                "niederlage" if (a["stars"], a["pct"]) < (b["stars"], b["pct"]) else "unentschieden")
        rounds.append({"day": i, "state": w["state"], "result": res, "opponent": b["name"],
                       "us": a["stars"], "them": b["stars"], "usPct": a["pct"], "themPct": b["pct"],
                       "final": bool(w.get("final")), "teamSize": w.get("teamSize"),
                       "apm": w.get("attacksPerMember") or 1,
                       "lineup": lineup_detail(w)})
        for m in w["members"]:
            p = players.setdefault(m["tag"], {"tag": m["tag"], "name": m["name"], "th": m.get("th"),
                                              "lineup": 0, "attacks": 0, "stars": 0, "pct": 0.0,
                                              "triples": 0, "missed": 0, "defStars": 0, "defs": 0})
            p["name"] = m["name"]
            p["lineup"] += 1
            for at in m["attacks"]:
                p["attacks"] += 1
                p["stars"] += at["stars"]
                p["pct"] += at["pct"]
                if at["stars"] == 3:
                    p["triples"] += 1
            if w.get("final") and not m["attacks"]:
                p["missed"] += 1
            for dfn in m.get("defenses", []):
                p["defs"] += 1
                p["defStars"] += dfn["stars"]
    ranking = sorted(players.values(), key=lambda p: (-p["stars"], -p["pct"]))
    out = {"season": season[:4] + "-" + season[4:6], "rounds": rounds, "players": ranking,
           "roster": None}
    if roster and roster.get("season", "")[:7].replace("-", "") == season:
        out["roster"] = roster["members"]
    return out


def cwl_prev_light(s):
    """Nur das Nötige der Vorwoche: Saison und Tage mit Aufstellung."""
    if not s:
        return None
    return {"season": s["season"], "rounds": s["rounds"]}


def lineup_detail(w):
    """Pro aufgestelltem Spieler: Rathaus, Angriffe [Sterne, %, Gegner-Rathaus] und beste gegnerische Attacke auf ihn."""
    out = {}
    for m in w["members"]:
        defs = m.get("defenses", [])
        best = max(defs, key=lambda d: (d["stars"], d["pct"])) if defs else None
        out[m["tag"]] = {
            "name": m["name"],
            "th": m.get("th"),
            # [Sterne, %, Rathaus des Gegners]
            "att": [[a["stars"], a["pct"], a.get("defTh")] for a in m["attacks"]],
            "def": [best["stars"], best["pct"]] if best else None,
        }
    return out


def regular_rounds(wars, n=6):
    """Die letzten normalen Kriege im selben Format wie die Liga-Tage."""
    reg = sorted([w for w in wars if w.get("kind") == "regular" and w.get("preparationStartTime")],
                 key=lambda w: w["preparationStartTime"])[-n:]
    return [{"day": i, "state": w["state"], "final": bool(w.get("final")),
             "teamSize": w.get("teamSize"), "apm": w.get("attacksPerMember") or 2,
             "opponent": w["opponent"]["name"], "end": w.get("endTime"),
             "lineup": lineup_detail(w)} for i, w in enumerate(reg, 1)]


def build_board(state, live, fetched_at):
    board = {"generated": iso(fetched_at), "clans": []}
    for clan_tag in CONFIG["clans"]:
        info = live.get(clan_tag, {}).get("info") or state.get("info", {}).get(clan_tag, {})
        cs = state.get("clans", {}).get(clan_tag, {})
        wars = load_records("wars", clan_tag)
        raids = load_records("raids", clan_tag)
        ws = war_member_stats(wars, CONFIG.get("recent_wars", 10))
        raids_all = sorted(raids, key=lambda r: r.get("startTime") or "")
        # für die Spielerwerte nur Wochenenden mit bekannter Teilnehmerliste
        raids_sorted = [r for r in raids_all if r.get("members")][-4:]
        gs_key = fetched_at.strftime("%Y-%m")

        members = []
        for mt, t in cs.get("members", {}).items():
            if not t.get("inClan"):
                continue
            w = ws.get(mt, {})
            raid_hist = []
            for r in raids_sorted:
                rm = next((x for x in r["members"] if x["tag"] == mt), None)
                raid_hist.append({
                    "start": r["startTime"], "state": r["state"],
                    "attacks": rm["attacks"] if rm else 0,
                    "limit": rm["limit"] if rm else 6,
                    "loot": rm["loot"] if rm else 0,
                })
            don = t.get("donations", {})
            cur = don.get("cur") or {}
            games = t.get("games", {})
            members.append({
                "tag": mt, "name": t.get("name"), "role": t.get("role"), "th": t.get("th"),
                "exp": t.get("exp"), "trophies": t.get("trophies"), "league": t.get("league"),
                "leagueIcon": t.get("leagueIcon"),
                "builderTrophies": t.get("builderTrophies"),
                "joinedAt": t.get("joinedAt"), "firstSeen": t.get("firstSeen"),
                "joins": t.get("joins", 1),
                "lastActive": t.get("lastActive"),
                "donations": cur.get("d", 0), "received": cur.get("r", 0),
                "donationsPrev": don.get("season", [])[-1:] or None,
                "profile": t.get("profile", {}),
                "war": w,
                "raids": raid_hist,
                "games": games.get(gs_key, {}).get("points"),
                "gamesHistory": {k: v.get("points") for k, v in games.items()},
                "capitalWeek": latest_capital_gold(t),
                "boosts": (t.get("profile") or {}).get("boosts", []),
            })

        def war_summary(w):
            res = "offen"
            if w.get("final"):
                a, b = w["us"], w["opponent"]
                if (a["stars"], a["pct"]) > (b["stars"], b["pct"]):
                    res = "sieg"
                elif (a["stars"], a["pct"]) < (b["stars"], b["pct"]):
                    res = "niederlage"
                else:
                    res = "unentschieden"
            apm = w.get("attacksPerMember") or 2
            missed = [{"name": m["name"], "tag": m["tag"], "missed": apm - len(m["attacks"])}
                      for m in w["members"] if len(m["attacks"]) < apm]
            return {
                "kind": w["kind"], "state": w["state"], "final": w.get("final"),
                "start": w.get("startTime"), "end": w.get("endTime"),
                "teamSize": w.get("teamSize"), "apm": apm,
                "us": w["us"], "opponent": w["opponent"], "result": res,
                "missed": missed,
            }

        wars_sorted = sorted(wars, key=lambda w: w.get("preparationStartTime") or "")
        lv = live.get(clan_tag, {})
        current = lv.get("current") or lv.get("cwl")
        current_detail = None
        if current:
            current_detail = war_summary(current)
            current_detail["members"] = current["members"]

        board["clans"].append({
            "tag": clan_tag,
            "name": info.get("name"),
            "badge": (info.get("badgeUrls") or {}).get("medium"),
            "level": info.get("clanLevel"),
            "members": info.get("members"),
            "warWins": info.get("warWins"), "warLosses": info.get("warLosses"),
            "warTies": info.get("warTies"), "warWinStreak": info.get("warWinStreak"),
            "warLeague": (info.get("warLeague") or {}).get("name"),
            "capitalLeague": (info.get("capitalLeague") or {}).get("name"),
            "capitalHall": (info.get("clanCapital") or {}).get("capitalHallLevel"),
            "points": info.get("clanPoints"), "isWarLogPublic": info.get("isWarLogPublic"),
            "memberList": members,
            "currentWar": current_detail,
            "wars": [war_summary(w) for w in wars_sorted[-20:]][::-1],
            "raids": [dict({k: r.get(k) for k in (
                "startTime", "endTime", "state", "capitalTotalLoot", "raidsCompleted",
                "totalAttacks", "offensiveReward", "defensiveReward")},
                participants=len(r["members"]),
                members=sorted(r["members"], key=lambda x: -x["loot"])) for r in raids_all][::-1],
            "cwl": with_standings(cwl_season(wars, state.get("cwlRoster", {}).get(clan_tag)),
                                  state.get("cwlStandings", {}).get(clan_tag)),
            # Vorwoche: entscheidet am ersten Liga-Tag, wer aussetzt (vergessen, schwächster letzter Tag)
            "cwlPrev": cwl_prev_light(cwl_season(wars, back=1)),
            "regularRounds": regular_rounds(wars),
            "log": cs.get("log", [])[-60:][::-1],
        })
    return board


def main():
    global TOKEN
    TOKEN = load_token()
    fetched_at = now_utc()
    state_path = os.path.join(DATA, "state.json")
    state = read_json(state_path, {})
    live = {}
    for clan_tag in CONFIG["clans"]:
        info = api("/clans/%s" % enc(clan_tag))
        if not info or "_error" in info:
            sys.exit("Clan %s nicht abrufbar: %s" % (clan_tag, info))
        state.setdefault("info", {})[clan_tag] = {k: v for k, v in info.items() if k != "memberList"}
        update_members(info, state, fetched_at)
        current, cwl, group, standings = fetch_wars(clan_tag, fetched_at)
        # angemeldete Liga-Teilnehmer der Saison merken
        if group and group.get("season") and standings:
            # Ligatabelle der Saison merken, die Gruppe verschwindet nach Ligaende aus der API
            state.setdefault("cwlStandings", {})[clan_tag] = {"season": group["season"], "table": standings}
        if group and group.get("season"):
            ours = next((c for c in group.get("clans", []) if c.get("tag") == clan_tag), None)
            if ours:
                state.setdefault("cwlRoster", {})[clan_tag] = {
                    "season": group["season"],
                    "members": [{"tag": m["tag"], "name": m.get("name"), "th": m.get("townHallLevel")}
                                for m in ours.get("members", [])],
                }
        fetch_raids(clan_tag)
        live[clan_tag] = {"info": info, "current": current, "cwl": cwl}
        print("%s: %d Mitglieder, Krieg: %s, CWL: %s" % (
            info.get("name"), info.get("members", 0),
            current["state"] if current else "-", cwl["state"] if cwl else "-"))
    state["lastFetch"] = iso(fetched_at)
    write_json(state_path, state)
    write_json(os.path.join(DATA, "board.json"), build_board(state, live, fetched_at))


if __name__ == "__main__":
    try:
        main()
    except Voruebergehend as e:
        # Kurze Störung: nichts speichern, Lauf trotzdem als erfolgreich beenden,
        # damit GitHub keine Fehler-Mail schickt. Der nächste Lauf holt alles nach.
        print("::warning::Übersprungen, Clash-API vorübergehend nicht erreichbar (%s)" % e)
        sys.exit(0)
