// Live-Abfrage für das Clan-Board: aktueller Krieg/Liga und Mitgliederliste.
// Der API-Schlüssel liegt nur hier (Umgebungsvariable COC_API_TOKEN), nie auf der Seite.

const BASE = "https://cocproxy.royaleapi.dev/v1";
const CLANS = ["#29PU080G", "#2PPGPGRL9"];
const ORIGINS = ["https://sven674.github.io", "http://localhost:8791", "http://localhost:8000"];

async function api(path) {
  const r = await fetch(BASE + path, {
    headers: { Authorization: "Bearer " + process.env.COC_API_TOKEN, Accept: "application/json" },
  });
  if (!r.ok) return { _error: r.status };
  const data = await r.json();
  // Supercell gibt Daten nur in Abständen neu heraus (Liga-Kriege: 10 Minuten).
  // max-age = Sekunden bis zur nächsten neuen Fassung.
  const maxAge = +((r.headers.get("cache-control") || "").match(/max-age=(\d+)/) || [])[1];
  if (maxAge >= 0 && data && typeof data === "object")
    Object.defineProperty(data, "_next", { value: new Date(Date.now() + maxAge * 1000).toISOString() });
  return data;
}

const enc = (t) => encodeURIComponent(t);

function compactWar(war, clanTag, kind) {
  const ours = war.clan && war.clan.tag === clanTag;
  const us = ours ? war.clan : war.opponent;
  const them = ours ? war.opponent : war.clan;
  const apm = war.attacksPerMember || (kind === "cwl" ? 1 : 2);
  const members = (us.members || []).map((m) => ({
    tag: m.tag, name: m.name, th: m.townhallLevel, pos: m.mapPosition,
    attacks: (m.attacks || []).map((a) => ({ stars: a.stars, pct: a.destructionPercentage })),
  }));
  return {
    kind, state: war.state, final: war.state === "warEnded", teamSize: war.teamSize, apm,
    start: war.startTime, end: war.endTime,
    us: { stars: us.stars || 0, pct: us.destructionPercentage || 0, attacks: us.attacks || 0 },
    opponent: { name: them.name, tag: them.tag, stars: them.stars || 0, pct: them.destructionPercentage || 0 },
    members,
  };
}

// Liefert den laufenden Ligatag (war) und die Vorbereitungsrunde (prep), deren
// Aufstellung sich noch ändern kann. prep.day ist der Ligatag (1-7).
async function currentCwl(clanTag) {
  const group = await api(`/clans/${enc(clanTag)}/currentwar/leaguegroup`);
  if (!group || group._error || !group.rounds) return { war: null, prep: null };
  // von der neuesten Runde rückwärts: laufender Kampftag vor Vorbereitung
  let prep = null;
  for (let i = group.rounds.length - 1; i >= 0; i--) {
    const tags = (group.rounds[i].warTags || []).filter((t) => t && t !== "#0");
    if (!tags.length) continue;
    const wars = await Promise.all(tags.map((t) => api(`/clanwarleagues/wars/${enc(t)}`)));
    const w = wars.find((x) => x && !x._error && (x.clan.tag === clanTag || x.opponent.tag === clanTag));
    if (!w) continue;
    if (w.state === "preparation") {
      if (!prep) prep = Object.assign(compactWar(w, clanTag, "cwl"), { day: i + 1, next: w._next });
      continue;
    }
    return { war: compactWar(w, clanTag, "cwl"), prep };
  }
  return { war: prep, prep };
}

async function clanLive(clanTag) {
  const [info, cur] = await Promise.all([
    api(`/clans/${enc(clanTag)}`),
    api(`/clans/${enc(clanTag)}/currentwar`),
  ]);
  if (!info || info._error) return { tag: clanTag, error: info && info._error };
  let war = null, cwlPrep = null;
  if (cur && !cur._error && cur.state && cur.state !== "notInWar") war = compactWar(cur, clanTag, "regular");
  else ({ war, prep: cwlPrep } = await currentCwl(clanTag));
  return {
    tag: clanTag,
    name: info.name, members: info.members, level: info.clanLevel, points: info.clanPoints,
    warWins: info.warWins, warLosses: info.warLosses, warTies: info.warTies, warWinStreak: info.warWinStreak,
    isWarLogPublic: info.isWarLogPublic,
    memberList: (info.memberList || []).map((m) => ({
      tag: m.tag, name: m.name, role: m.role, th: m.townHallLevel, exp: m.expLevel,
      trophies: m.trophies, league: m.league && m.league.name,
      donations: m.donations, received: m.donationsReceived,
    })),
    currentWar: war,
    cwlPrep: cwlPrep && { day: cwlPrep.day, opponent: cwlPrep.opponent.name, next: cwlPrep.next,
                          lineup: cwlPrep.members.map((m) => ({ tag: m.tag, name: m.name })) },
  };
}

// Absicherung, falls GitHubs Zeitplan ausfällt: ist der letzte Datenabruf älter als
// 30 Minuten und läuft gerade keiner, wird er beim Seitenaufruf angestoßen.
const REPO = "Sven674/clan-board";
async function kickUpdate() {
  const tok = process.env.GH_DISPATCH_TOKEN;
  if (!tok) return "kein Token";
  const h = { Authorization: "Bearer " + tok, Accept: "application/vnd.github+json",
              "User-Agent": "clan-board-live" };
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/update.yml/runs?per_page=1`, { headers: h });
  if (!r.ok) return "Abfrage " + r.status;
  const run = ((await r.json()).workflow_runs || [])[0];
  if (run && (run.status !== "completed" || Date.now() - Date.parse(run.created_at) < 30 * 60 * 1000)) return "aktuell";
  const d = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/update.yml/dispatches`, {
    method: "POST", headers: h, body: JSON.stringify({ ref: "main" }),
  });
  return d.status === 204 ? "angestoßen" : "Start " + d.status;
}

module.exports = async (req, res) => {
  const origin = req.headers.origin;
  if (ORIGINS.includes(origin)) res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  if (req.method === "OPTIONS") return res.status(204).end();
  try {
    const [clans, update] = await Promise.all([
      Promise.all(CLANS.map(clanLive)),
      kickUpdate().catch(() => "Fehler"),
    ]);
    res.setHeader("Cache-Control", "public, s-maxage=60, stale-while-revalidate=30");
    res.status(200).json({ generated: new Date().toISOString(), update, clans });
  } catch (e) {
    res.setHeader("Cache-Control", "no-store");
    res.status(502).json({ error: "Abruf fehlgeschlagen" });
  }
};
