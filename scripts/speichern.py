"""Schreibt Angaben der Führung aus dem Board (Umgebungsvariable PAYLOAD) nach data/fuehrung.json.

Aufbau je Clan-Tag:
  "JJJJ-MM": {"anzahl": int|None, "leistung": int (nur Ü40 Pur 2), "verzicht": [Tags], "bonus": [Tags]}   Bonus je Ligasaison
  "freiwillig": {"liga:JJJJ-MM:Tag" | "krieg:...": [Tags]}              freiwillige Aussetzer
  "erledigt": {"liga:JJJJ-MM:Tag" | "krieg:...": {"by": Tag, "at": Zeit}} Aufstellung fertig gemeldet
  "getauscht": {Spieler-Tag: Zeit}                                      Dorf getauscht (Zähler ab dann neu)
"""
import json
import os
import re

TAG = re.compile(r"^#[0289PYLQGRJCUV]{3,12}$")
SEASON = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KEY = re.compile(r"^(liga|krieg):[0-9A-Za-z:.\-]{1,40}$")
CLANS = {"#29PU080G", "#2PPGPGRL9"}
PATH = os.path.join(os.path.dirname(__file__), "..", "data", "fuehrung.json")
KEEP_FREIWILLIG = 30
KEEP_GETAUSCHT = 100


def tags(x):
    if not isinstance(x, list) or len(x) > 60 or not all(isinstance(t, str) and TAG.match(t) for t in x):
        raise SystemExit("Ungültige Tags")
    return sorted(set(x))


def main():
    p = json.loads(os.environ["PAYLOAD"])
    clan = p.get("clan")
    if clan not in CLANS:
        raise SystemExit("Ungültiger Clan")
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    c = data.setdefault(clan, {})

    if p.get("type") == "bonus":
        season, prev, anzahl = p.get("season"), p.get("prevSeason"), p.get("anzahl")
        if not SEASON.match(season or "") or not SEASON.match(prev or ""):
            raise SystemExit("Ungültige Saison")
        if anzahl is not None and not (isinstance(anzahl, int) and 0 <= anzahl <= 50):
            raise SystemExit("Ungültige Anzahl")
        leistung = p.get("leistung")
        if leistung is not None and not (isinstance(leistung, int) and 0 <= leistung <= 50):
            raise SystemExit("Ungültige Anzahl Leistungsboni")
        c[season] = {"anzahl": anzahl, "verzicht": tags(p.get("verzicht")), "bonus": tags(p.get("bonus"))}
        if leistung is not None:
            c[season]["leistung"] = leistung
        c.setdefault(prev, {"anzahl": None, "verzicht": []})["bonus"] = tags(p.get("prevBonus"))
    elif p.get("type") == "freiwillig":
        key = p.get("key") or ""
        if not KEY.match(key):
            raise SystemExit("Ungültiger Schlüssel")
        fw = c.setdefault("freiwillig", {})
        fw.pop(key, None)
        fw[key] = tags(p.get("tags"))
        for old in list(fw)[:-KEEP_FREIWILLIG]:
            del fw[old]
    elif p.get("type") == "erledigt":
        key, by, at = p.get("key") or "", p.get("by"), p.get("at") or ""
        if not KEY.match(key) or (by is not None and not TAG.match(by)) \
                or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", at):
            raise SystemExit("Ungültige Fertig-Meldung")
        er = c.setdefault("erledigt", {})
        er.pop(key, None)
        if by:
            er[key] = {"by": by, "at": at}
        for old in list(er)[:-KEEP_FREIWILLIG]:
            del er[old]
    elif p.get("type") == "getauscht":
        tag, at = p.get("tag") or "", p.get("at") or ""
        if not TAG.match(tag) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", at):
            raise SystemExit("Ungültige Tausch-Meldung")
        gt = c.setdefault("getauscht", {})
        gt.pop(tag, None)
        gt[tag] = at
        for old in list(gt)[:-KEEP_GETAUSCHT]:
            del gt[old]
    else:
        raise SystemExit("Unbekannte Art")

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
