// groovyeverywhere online demo. Two ways in: bring a song (record 30 s or upload a clip; the API analyses it with
// the student's Essentia models) or start from a pool song. The API is a Hugging Face Space (api/main.py), address in
// config.js. Rendering follows the booth page (demo.html): rankings against the pool, never "100%".
const API = (window.VITE_API_BASE || "http://localhost:8080").replace(/\/+$/, "");
const $ = id => document.getElementById(id);
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let POOL = 0, current = null, busy = false, ready = false;   // current = {kind: "pool", key} or {kind: "clip", token}

// The AI Lodge card, shown when a visitor reaches the analysis limit (HTTP 429). Links, labels and order are fixed.
const CTA = {
  name: "groovyeverywhere", emoji: "🎧", accent: "#c2336f",
  headline: "Your taste just found its match!",
  description: "Want to build AI that understands music by mood, rhythm and sound? AI Lodge gives music lovers who code the team and the stage to ship their ideas.",
  programmeLink: "https://www.smubia.com/ailodge",
  showcaseLink: "https://www.smubia.com/Projects",
  githubLink: "https://github.com/smubia-projects/ail-ay2627-s1-ryan-groovyeverywhere",
};

class Handled extends Error {}

async function api(path, opts = {}) {
  let r;
  try { r = await fetch(API + path, opts); }
  catch { throw new Error("We couldn't reach the demo server. Check your connection and try again."); }
  let d = {};
  try { d = await r.json(); } catch { /* not JSON: a platform error page */ }
  if (r.status === 429) { showCta(); throw new Handled(); }
  if (r.status === 503) { showPaused(d.detail?.message || ""); throw new Handled(); }
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong. Please try again.");
  return d;
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function message(id, text, kind) { $(id).innerHTML = text ? `<div class="msg ${kind || ""}">${esc(text)}</div>` : ""; }

function setBusy(on, label) {
  busy = on;
  $("go").disabled = on || !ready;
  $("recBtn").disabled = (on && !recorder) || !ready;
  $("fileLbl").setAttribute("aria-disabled", on || !ready ? "true" : "false");
  document.querySelectorAll("#chips button, #langs button, #samples button, .cand").forEach(b => b.disabled = on);
  clearInterval(setBusy.t);
  $("progress").classList.toggle("on", on && !!label);
  if (on && label) {
    const t0 = Date.now(); $("stageTxt").textContent = label; $("elapsed").textContent = "";
    setBusy.t = setInterval(() => { $("elapsed").textContent = Math.round((Date.now() - t0) / 1000) + " s"; }, 1000);
  }
}

async function status() {
  try {
    const s = await api("/api/status");
    if (!s.ready) {
      $("dot").className = "dot";
      $("lightTxt").textContent = s.error ? "the song pool did not load" : (s.stage || "starting") + "…";
      if (!s.error) setTimeout(status, 5000);
      return;
    }
    ready = true; POOL = s.pool;
    $("dot").className = "dot ready";
    $("lightTxt").textContent = `ready · ${s.pool.toLocaleString()} songs`;
    setBusy(false);
    const d = await api("/api/samples");
    $("samples").innerHTML = d.songs.map((s, i) => `<button class="chipbtn" type="button" data-i="${i}" title="${esc(s.title)} · ${esc(s.artist)}">${esc((s.artist || s.title).slice(0, 26))}</button>`).join("");
    $("samples").querySelectorAll("button").forEach(b => b.onclick = () => pick(d.songs[+b.dataset.i]));
  } catch {
    $("dot").className = "dot";
    $("lightTxt").textContent = "waking the demo server up (this can take a few minutes)…";
    setTimeout(status, 8000);
  }
}

// ---- bring a song
let recorder = null, chunks = [], stopTimer = null;
$("recBtn").onclick = async () => {
  if (recorder) { recorder.stop(); return; }
  if (busy || !ready) return;
  message("clipMsg", "");
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } }); }
  catch { message("clipMsg", "The microphone isn't available. Allow it in your browser, or upload a clip instead.", "err"); return; }
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = () => {
    stream.getTracks().forEach(t => t.stop()); clearInterval(stopTimer);
    $("recBtn").classList.remove("rec"); $("recBtn").textContent = "🎙 record 30 seconds"; $("recTxt").textContent = "";
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    recorder = null;
    if (blob.size < 2000) { setBusy(false); message("clipMsg", "The recording was too short. Try again.", "warn"); return; }
    sendClip(blob, "recording." + (blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm"));
  };
  recorder.start();
  setBusy(true);
  $("recBtn").disabled = false; $("recBtn").classList.add("rec");
  let left = 30;
  $("recBtn").textContent = "■ stop"; $("recTxt").textContent = `recording… ${left} s`;
  stopTimer = setInterval(() => { left -= 1; $("recTxt").textContent = `recording… ${left} s`; if (left <= 0 && recorder) recorder.stop(); }, 1000);
};
$("file").onchange = () => {
  const f = $("file").files[0];
  $("file").value = "";
  if (!f || busy) return;
  if (f.size > 15 * 1024 * 1024) { message("clipMsg", "That file is over 15 MB. A minute of the song is plenty.", "warn"); return; }
  sendClip(f, f.name);
};

async function sendClip(blob, name) {
  message("clipMsg", ""); setBusy(true, "listening to your song (analysing with the audio models)…");
  try {
    const fd = new FormData();
    fd.append("audio", blob, name);
    fd.append("features", chosen("chips", "f").join("+") || "mood+rhythm+instruments");
    fd.append("languages", chosen("langs", "l").join("+") || "english+chinese+korean");
    const d = await api("/api/clip", { method: "POST", body: fd });
    current = { kind: "clip", token: d.token };
    render(d, true);
  } catch (e) { if (!(e instanceof Handled)) message("clipMsg", e.message, "err"); }
  finally { setBusy(false); }
}

// ---- start from a pool song
async function search() {
  const q = $("q").value.trim();
  if (!q || busy || !ready) return;
  message("msg", ""); setBusy(true);
  try {
    const d = await api("/api/search?q=" + encodeURIComponent(q));
    const el = $("cands");
    if (!d.songs.length) { el.classList.remove("on"); el.innerHTML = ""; message("msg", `No pool song matches "${q}". Try another title or artist, or play us the song instead.`, "warn"); return; }
    el.innerHTML = "<h3>Is it one of these?</h3>" + d.songs.map((c, i) =>
      `<button class="cand" type="button" data-i="${i}"><span class="ct${c.yt ? "" : " none"}" ${c.yt ? `style="background-image:url(https://i.ytimg.com/vi/${esc(c.yt)}/mqdefault.jpg)"` : ""}>${c.yt ? "" : "♪"}</span>
        <span><b>${esc(c.title)}</b><span>${esc(c.artist)}</span></span><span class="badge">instant</span></button>`).join("");
    el.classList.add("on");
    el.querySelectorAll(".cand").forEach(b => b.onclick = () => pick(d.songs[+b.dataset.i]));
  } catch (e) { if (!(e instanceof Handled)) message("msg", e.message, "err"); }
  finally { setBusy(false); }
}

function chosen(id, attr) { return [...document.querySelectorAll(`#${id} button`)].filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.dataset[attr]); }

async function pick(s) {
  $("cands").classList.remove("on"); $("cands").innerHTML = "";
  current = { kind: "pool", key: s.key };
  await rerank(true);
}

async function rerank(fresh) {
  if (!current || busy) return;
  const features = chosen("chips", "f"), languages = chosen("langs", "l");
  if (!features.length || !languages.length) { message("msg", "Choose at least one feature and one language.", "warn"); return; }
  message("msg", ""); setBusy(true);
  try {
    const d = current.kind === "clip"
      ? await postJSON("/api/refine", { token: current.token, features, languages })
      : await postJSON("/api/recommend", { key: current.key, features, languages });
    render(d, fresh);
  } catch (e) { if (!(e instanceof Handled)) message("msg", e.message, "err"); }
  finally { setBusy(false); }
}

function render(d, fresh) {
  document.body.classList.add("has-results");
  $("results").classList.add("on");
  if (d.input) {
    $("nowTitle").textContent = d.input.title;
    $("nowArtist").textContent = d.input.kind === "clip" ? `analysed in ${d.input.seconds} s` : d.input.artist;
    renderHeard(d.heard);
  }
  $("warn").innerHTML = d.warning ? `<div class="msg warn">${esc(d.warning)}</div>` : "";
  renderList("listA", d.results.A, "A");
  renderList("listB", d.results.B, "B");
  if (fresh) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderHeard(h) {
  const el = $("heard");
  if (!h || !h.mood) { el.innerHTML = ""; return; }
  const chips = [`<span class="hchip"><b>mood</b>${esc(h.mood)} <i>(happiness ${esc(h.happiness)} · energy ${esc(h.energy)} of 9)</i></span>`,
                 `<span class="hchip"><b>tempo</b>${esc(h.tempo)}</span>`];
  if (h.instruments && h.instruments.length) chips.push(`<span class="hchip"><b>instruments</b>${h.instruments.map(esc).join(", ")}</span>`);
  el.innerHTML = '<span class="hchip" style="border:0;background:none;padding-left:0"><b>what we heard</b></span>' + chips.join("");
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

// ---- 429 card and 503 notice
function modal(html, label) {
  const box = $("cta");
  box.innerHTML = `<div class="ail-backdrop" id="ailBack"><div class="ail-card" role="dialog" aria-modal="true" aria-label="${esc(label)}">${html}</div></div>`;
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
  box.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  $("ailBack").onclick = e => { if (e.target.id === "ailBack") close(); };
  focusables[0]?.focus();
}

function showCta() {
  modal(`<div class="ail-top"><div class="ail-emoji">${CTA.emoji}</div><div class="ail-head">${esc(CTA.headline)}</div>
      <div class="ail-desc">${esc(CTA.description)}</div></div>
    <div class="ail-body">
      <a class="ail-btn primary" href="${CTA.programmeLink}" target="_blank" rel="noopener noreferrer">Join AI Lodge<span>→</span></a>
      <a class="ail-btn" href="${CTA.showcaseLink}" target="_blank" rel="noopener noreferrer">Explore other projects<span>→</span></a>
      <a class="ail-btn" href="${CTA.githubLink}" target="_blank" rel="noopener noreferrer">View on GitHub<span>→</span></a>
    </div>
    <button class="ail-later" type="button" data-close>Maybe later</button>`, `${CTA.name} rate limit reached`);
}

function showPaused(msg) {
  modal(`<div class="ail-body" style="text-align:center;padding-top:28px"><div class="ail-emoji">⏸️</div><div class="ail-head">Demo temporarily paused</div>
      <div class="ail-desc" style="color:#aaa">${esc(msg || "This demo is temporarily paused. Check back soon.")}</div></div>
    <button class="ail-later" type="button" data-close>Got it</button>`, "Demo paused");
}

document.querySelectorAll("#chips button, #langs button").forEach(b => b.onclick = () => {
  b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
  rerank(false);
});
$("go").onclick = search;
$("q").addEventListener("keydown", e => { if (e.key === "Enter") search(); });
setBusy(false);
status();
