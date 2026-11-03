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
  return r.json();
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

async function currentCwl(clanTag) {
  const group = await api(`/clans/${enc(clanTag)}/currentwar/leaguegroup`);
  if (!group || group._error || !group.rounds) return null;
  // von der neuesten Runde rückwärts: laufender Kampftag vor Vorbereitung
  let prep = null;
  for (let i = group.rounds.length - 1; i >= 0; i--) {
    const tags = (group.rounds[i].warTags || []).filter((t) => t && t !== "#0");
    if (!tags.length) continue;
    const wars = await Promise.all(tags.map((t) => api(`/clanwarleagues/wars/${enc(t)}`)));
    const w = wars.find((x) => x && !x._error && (x.clan.tag === clanTag || x.opponent.tag === clanTag));
    if (!w) continue;
    if (w.state === "inWar") return compactWar(w, clanTag, "cwl");
    if (w.state === "preparation") { prep = prep || compactWar(w, clanTag, "cwl"); continue; }
    return prep || compactWar(w, clanTag, "cwl");
  }
  return prep;
}

async function clanLive(clanTag) {
  const [info, cur] = await Promise.all([
    api(`/clans/${enc(clanTag)}`),
    api(`/clans/${enc(clanTag)}/currentwar`),
  ]);
  if (!info || info._error) return { tag: clanTag, error: info && info._error };
  let war = null;
  if (cur && !cur._error && cur.state && cur.state !== "notInWar") war = compactWar(cur, clanTag, "regular");
  else war = await currentCwl(clanTag);
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
  };
}

module.exports = async (req, res) => {
  const origin = req.headers.origin;
  if (ORIGINS.includes(origin)) res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  if (req.method === "OPTIONS") return res.status(204).end();
  try {
    const clans = await Promise.all(CLANS.map(clanLive));
    res.setHeader("Cache-Control", "public, s-maxage=60, stale-while-revalidate=30");
    res.status(200).json({ generated: new Date().toISOString(), clans });
  } catch (e) {
    res.setHeader("Cache-Control", "no-store");
    res.status(502).json({ error: "Abruf fehlgeschlagen" });
  }
};
