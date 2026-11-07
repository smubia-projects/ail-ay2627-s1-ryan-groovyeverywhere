// groovyeverywhere online demo: search the pool, pick a song, get the two lists from the API (api/main.py on Cloud
// Run, address in config.js). Rendering follows the booth page (demo.html): rankings against the pool, never "100%".
const API = (window.VITE_API_BASE || "http://localhost:8080").replace(/\/+$/, "");
const $ = id => document.getElementById(id);
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let POOL = 0, current = null, busy = false;

// The AI Lodge card: shown once, after a few searches (this demo calls no AI model, so nothing is rate limited).
const CTA_AFTER = 3, CTA_KEY = "groovyeverywhere.ailodge-cta";
const CTA = {
  programmeLink: "https://www.smubia.com/ailodge",
  showcaseLink: "https://www.smubia.com/Projects",
  githubLink: "https://github.com/smubia-projects/ail-ay2627-s1-ryan-groovyeverywhere",
};

async function api(path, body) {
  const r = await fetch(API + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  let d = {};
  try { d = await r.json(); } catch { /* not JSON: a platform error page */ }
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong. Please try again.");
  return d;
}

function message(text, kind) { $("msg").innerHTML = text ? `<div class="msg ${kind || ""}">${esc(text)}</div>` : ""; }

function setBusy(on) {
  busy = on;
  $("go").disabled = on || !POOL;
  document.querySelectorAll("#chips button, #langs button, #samples button, .cand").forEach(b => b.disabled = on);
}

async function status() {
  try {
    const s = await api("/api/status");
    POOL = s.pool;
    $("dot").className = "dot ready";
    $("lightTxt").textContent = `ready · ${s.pool.toLocaleString()} songs`;
    $("go").disabled = false;
    const d = await api("/api/samples");
    $("samples").innerHTML = d.songs.map((s, i) => `<button class="chipbtn" type="button" data-i="${i}" title="${esc(s.title)} · ${esc(s.artist)}">${esc((s.artist || s.title).slice(0, 26))}</button>`).join("");
    $("samples").querySelectorAll("button").forEach(b => b.onclick = () => pick(d.songs[+b.dataset.i]));
  } catch {
    $("dot").className = "dot";
    $("lightTxt").textContent = "the song pool is starting up: retrying…";
    setTimeout(status, 4000);
  }
}

async function search() {
  const q = $("q").value.trim();
  if (!q || busy) return;
  message(""); setBusy(true);
  try {
    const d = await api("/api/search?q=" + encodeURIComponent(q));
    const el = $("cands");
    if (!d.songs.length) { el.classList.remove("on"); el.innerHTML = ""; message(`No pool song matches "${q}". Try another title or artist.`, "warn"); return; }
    el.innerHTML = "<h3>Is it one of these?</h3>" + d.songs.map((c, i) =>
      `<button class="cand" type="button" data-i="${i}"><span class="ct${c.yt ? "" : " none"}" ${c.yt ? `style="background-image:url(https://i.ytimg.com/vi/${esc(c.yt)}/mqdefault.jpg)"` : ""}>${c.yt ? "" : "♪"}</span>
        <span><b>${esc(c.title)}</b><span>${esc(c.artist)}</span></span><span class="badge">in the pool</span></button>`).join("");
    el.classList.add("on");
    el.querySelectorAll(".cand").forEach(b => b.onclick = () => pick(d.songs[+b.dataset.i]));
  } catch (e) { message(e.message, "err"); }
  finally { setBusy(false); }
}

function chosen(id, attr) { return [...document.querySelectorAll(`#${id} button`)].filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.dataset[attr]); }

async function pick(s) {
  current = s;
  $("cands").classList.remove("on"); $("cands").innerHTML = "";
  await recommend(true);
}

async function recommend(fresh) {
  if (!current || busy) return;
  const features = chosen("chips", "f"), languages = chosen("langs", "l");
  if (!features.length || !languages.length) { message("Choose at least one feature and one language.", "warn"); return; }
  message(""); setBusy(true);
  try {
    const d = await api("/api/recommend", { key: current.key, features, languages });
    document.body.classList.add("has-results");
    $("results").classList.add("on");
    $("nowTitle").textContent = d.input.title;
    $("nowArtist").textContent = d.input.artist;
    renderHeard(d.input.heard);
    renderList("listA", d.results.A, "A");
    renderList("listB", d.results.B, "B");
    if (fresh) { $("results").scrollIntoView({ behavior: "smooth", block: "start" }); countUse(); }
  } catch (e) { message(e.message, "err"); }
  finally { setBusy(false); }
}

function renderHeard(h) {
  const el = $("heard");
  if (!h || !h.mood) { el.innerHTML = ""; return; }
  el.innerHTML = '<span class="hchip" style="border:0;background:none;padding-left:0"><b>what we heard</b></span>' +
    `<span class="hchip"><b>mood</b>${esc(h.mood)} <i>(happiness ${esc(h.happiness)} · energy ${esc(h.energy)} of 9)</i></span>` +
    `<span class="hchip"><b>tempo</b>${esc(h.tempo)}</span>`;
}

function pctText(v) {                                     // one decimal near the top (99.4 vs 99.9), never "100" (that would read as identical)
  v = Math.min(99.9, Math.max(0, +v || 0));
  return v >= 95 ? v.toFixed(1) : String(Math.round(v));
}
function bar(label, v) {
  return `<span>${label}</span><span class="track" title="closer than ${pctText(v)}% of the pool on ${label}"><i style="width:${Math.max(2, Math.min(100, v))}%"></i></span><span>${pctText(v)}</span>`;
}

function renderList(id, items, which) {
  const el = $(id);
  if (!items || !items.length) { el.innerHTML = '<div class="empty">No song passed every check for this starting song. Fewer features chosen usually finds some.</div>'; return; }
  el.innerHTML = items.map((r, i) => {
    const thumb = r.yt ? `style="background-image:url(https://i.ytimg.com/vi/${esc(r.yt)}/mqdefault.jpg)"` : "";
    const link = /^https:\/\//.test(r.link || "") ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">open on YouTube</a>` : "";
    return `<div class="rec" data-i="${i}">
      <button class="thumb" type="button" ${thumb} aria-label="Play ${esc(r.title)}" ${r.yt ? "" : "disabled"}></button>
      <div>
        <h4>${esc(r.title)}</h4>
        <div class="artist">${esc(r.artist)}</div>
        <div class="match" title="${which === "B" ? "combined match" : "sound"}: closer to your song than ${pctText(r.match)}% of the ${POOL ? POOL.toLocaleString() + " " : ""}pool songs">closer than ${pctText(r.match)}% of the pool${r.popularity ? " · " + esc(r.popularity) : ""}</div>
        <div class="bars">${bar("sound", r.sound)}${bar("mood", r.mood)}${bar("beat", r.rhythm)}${bar("instruments", r.instruments)}</div>
        <div class="actions">${link}</div>
      </div>
      <div class="player"></div>
    </div>`;
  }).join("");
  el.querySelectorAll(".rec").forEach(card => {
    const r = items[+card.dataset.i];
    card.querySelector(".thumb").onclick = () => {
      const box = card.querySelector(".player");
      box.innerHTML = box.innerHTML ? "" : `<iframe src="https://www.youtube.com/embed/${encodeURIComponent(r.yt)}?autoplay=1" allow="autoplay; encrypted-media" allowfullscreen title="${esc(r.title)}"></iframe>`;
    };
  });
}

function countUse() {
  let n = 0, shown = false;
  try { n = +(localStorage.getItem(CTA_KEY + ".uses") || 0) + 1; localStorage.setItem(CTA_KEY + ".uses", String(n)); shown = localStorage.getItem(CTA_KEY + ".shown") === "1"; }
  catch { return; }                                       // storage blocked: skip the card rather than show it every time
  if (n < CTA_AFTER || shown) return;
  try { localStorage.setItem(CTA_KEY + ".shown", "1"); } catch { /* shown once this page load */ }
  showCta(n);
}

function showCta(n) {
  const box = $("cta");
  box.innerHTML = `<div class="ail-backdrop" id="ailBack"><div class="ail-card" role="dialog" aria-modal="true" aria-label="groovyeverywhere: AI Lodge">
    <div class="ail-top"><div class="ail-emoji">🎧</div><div class="ail-head">Found some new favourites?</div>
      <div class="ail-desc">You've explored ${n} songs' neighbours, matched on sound, mood, rhythm and instruments across about 9,000 songs. Want to build projects like this? Join the AI Lodge.</div></div>
    <div class="ail-body">
      <a class="ail-btn primary" href="${CTA.programmeLink}" target="_blank" rel="noopener noreferrer">Join AI Lodge<span>→</span></a>
      <a class="ail-btn" href="${CTA.showcaseLink}" target="_blank" rel="noopener noreferrer">Explore other projects<span>→</span></a>
      <a class="ail-btn" href="${CTA.githubLink}" target="_blank" rel="noopener noreferrer">View on GitHub<span>→</span></a>
    </div>
    <button class="ail-later" type="button" id="ailLater">Maybe later</button></div></div>`;
  const close = () => { box.innerHTML = ""; document.removeEventListener("keydown", onKey); };
  const focusables = [...box.querySelectorAll("a, button")];
  const onKey = e => {
    if (e.key === "Escape") close();
    if (e.key !== "Tab") return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey);
  $("ailLater").onclick = close;
  $("ailBack").onclick = e => { if (e.target.id === "ailBack") close(); };
  focusables[0].focus();
}

document.querySelectorAll("#chips button, #langs button").forEach(b => b.onclick = () => {
  b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
  recommend(false);
});
$("go").onclick = search;
$("q").addEventListener("keydown", e => { if (e.key === "Enter") search(); });
status();
