# Ü40 Pur Clan-Board

Statistik-Board für die Clans Ü40 Pur (#29PU080G) und Ü40 Pur 2 (#2PPGPGRL9).

- `scripts/fetch.py` holt alle 30 Minuten (GitHub Actions) die Daten über die offizielle Clash-of-Clans-API via RoyaleAPI-Proxy und speichert den Verlauf in `data/`.
- `index.html` zeigt `data/board.json` an.
- API-Schlüssel: auf developer.clashofclans.com mit IP `45.79.218.79` (RoyaleAPI-Proxy), als Repo-Secret `COC_API_TOKEN` hinterlegt.
- Lokal testen: `COC_API_TOKEN_FILE=~/.config/clan-board/token python3 scripts/fetch.py`, dann `python3 -m http.server` und `localhost:8000` öffnen.

Clans ändern: `config.json`.
