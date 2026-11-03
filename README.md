# Ü40 Pur Clan-Board

Statistik-Board für die Clans Ü40 Pur (#29PU080G) und Ü40 Pur 2 (#2PPGPGRL9).

- `scripts/fetch.py` holt alle 30 Minuten (GitHub Actions) die Daten über die offizielle Clash-of-Clans-API via RoyaleAPI-Proxy und speichert den Verlauf in `data/`.
- `index.html` zeigt `data/board.json` an.
- API-Schlüssel: auf developer.clashofclans.com mit IP `45.79.218.79` (RoyaleAPI-Proxy), als Repo-Secret `COC_API_TOKEN` hinterlegt.
- Lokal testen: `COC_API_TOKEN_FILE=~/.config/clan-board/token python3 scripts/fetch.py`, dann `python3 -m http.server` und `localhost:8000` öffnen.

Clans ändern: `config.json`.

## Live-Abfrage (Vercel)

`live-api/` ist eine kleine Serverfunktion bei Vercel (Projekt `clan-board-live`, https://clan-board-live.vercel.app/api/live). Sie liefert beim Seitenaufruf den aktuellen Krieg und die Mitgliederliste, 60 Sekunden zwischengespeichert. Fällt sie aus, zeigt die Seite den 30-Minuten-Stand.

**Schlüssel erneuern:** an ZWEI Stellen tauschen: GitHub-Secret `COC_API_TOKEN` und Vercel-Umgebungsvariable `COC_API_TOKEN` (danach `npx vercel deploy --prod` in `live-api/`).

**Absicherung Zeitplan:** GitHubs Zeitplan startet unzuverlässig. Die Live-Funktion stößt deshalb beim Seitenaufruf den Abruf an, wenn der letzte älter als 30 Minuten ist. Dafür liegt bei Vercel `GH_DISPATCH_TOKEN` (Fine-grained Token „Clan-Board-Ausloeser“, nur dieses Repo, nur Actions).

## Angaben der Führung (Bonus, freiwillige Aussetzer)

Im Liga-Tab kann die Führung mit PIN eintragen: Anzahl Boni, wer verzichtet, wer einen Bonus bekam (aktuelle und letzte Saison) und freiwillige Aussetzer für den nächsten Liga-Tag bzw. Krieg.

Ablauf: Seite → Vercel `api/speichern` (prüft PIN `BONUS_PIN`) → startet Workflow `speichern.yml` → `scripts/speichern.py` schreibt `data/fuehrung.json` → nach ca. 2 Minuten für alle sichtbar.

**PIN ändern:** Vercel, Projekt `clan-board-live`, Settings, Environment Variables, `BONUS_PIN`. Danach `npx vercel deploy --prod` in `live-api/`.
