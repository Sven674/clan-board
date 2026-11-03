// Speichert Angaben der Führung: Bonus (Anzahl, Verzicht, erhaltene Boni), freiwillige Aussetzer
// und die Fertig-Meldung für die Aufstellung.
// Prüft die PIN (Umgebungsvariable BONUS_PIN) und stößt den GitHub-Workflow speichern.yml an,
// der data/fuehrung.json ins Repo schreibt.

const crypto = require("crypto");

const REPO = "Sven674/clan-board";
const CLANS = ["#29PU080G", "#2PPGPGRL9"];
const ORIGINS = ["https://sven674.github.io", "http://localhost:8791", "http://localhost:8000"];
const TAG = /^#[0289PYLQGRJCUV]{3,12}$/;
const SEASON = /^\d{4}-(0[1-9]|1[0-2])$/;
const KEY = /^(liga|krieg):[0-9A-Za-z:.\-]{1,40}$/;

function pinOk(given) {
  const want = process.env.BONUS_PIN || "";
  const a = crypto.createHash("sha256").update(String(given || "")).digest();
  const b = crypto.createHash("sha256").update(want).digest();
  return want.length > 0 && crypto.timingSafeEqual(a, b);
}

const tags = (x) =>
  Array.isArray(x) && x.length <= 60 && x.every((t) => typeof t === "string" && TAG.test(t))
    ? [...new Set(x)].sort() : null;

function clean(b) {
  const clan = CLANS.includes(b.clan) ? b.clan : null;
  if (!clan) return null;
  if (b.type === "bonus") {
    const c = {
      type: "bonus", clan,
      season: SEASON.test(b.season || "") ? b.season : null,
      anzahl: b.anzahl === null || (Number.isInteger(b.anzahl) && b.anzahl >= 0 && b.anzahl <= 50) ? b.anzahl : undefined,
      verzicht: tags(b.verzicht), bonus: tags(b.bonus),
      prevSeason: SEASON.test(b.prevSeason || "") ? b.prevSeason : null,
      prevBonus: tags(b.prevBonus),
    };
    return c.season && c.anzahl !== undefined && c.verzicht && c.bonus && c.prevSeason && c.prevBonus ? c : null;
  }
  if (b.type === "erledigt") {
    const c = { type: "erledigt", clan, key: KEY.test(b.key || "") ? b.key : null,
                by: b.by === null ? null : (typeof b.by === "string" && TAG.test(b.by) ? b.by : undefined),
                at: new Date().toISOString().slice(0, 19) + "Z" };
    return c.key && c.by !== undefined ? c : null;
  }
  if (b.type === "freiwillig") {
    const c = { type: "freiwillig", clan, key: KEY.test(b.key || "") ? b.key : null, tags: tags(b.tags) };
    return c.key && c.tags ? c : null;
  }
  return null;
}

module.exports = async (req, res) => {
  const origin = req.headers.origin;
  if (ORIGINS.includes(origin)) res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Nur POST" });

  if (!process.env.BONUS_PIN) return res.status(503).json({ error: "PIN ist noch nicht eingerichtet" });
  const b = req.body || {};
  if (!pinOk(b.pin)) {
    await new Promise((r) => setTimeout(r, 1500));
    return res.status(403).json({ error: "PIN falsch" });
  }
  const c = clean(b);
  if (!c) return res.status(400).json({ error: "Ungültige Angaben" });

  const d = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/speichern.yml/dispatches`, {
    method: "POST",
    headers: { Authorization: "Bearer " + process.env.GH_DISPATCH_TOKEN, Accept: "application/vnd.github+json",
               "User-Agent": "clan-board-live" },
    body: JSON.stringify({ ref: "main", inputs: { payload: JSON.stringify(c) } }),
  });
  if (d.status !== 204) return res.status(502).json({ error: "Speichern fehlgeschlagen (" + d.status + ")" });
  return res.status(202).json({ ok: true });
};
