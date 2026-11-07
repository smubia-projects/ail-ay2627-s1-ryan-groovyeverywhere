"""groovyeverywhere demo API (Hugging Face Space, Docker, port 8080). API only: the page is on Vercel (web/).

Two ways in, both answered by the student's own code, unchanged:
  * bring a song: a visitor uploads or records a clip; capture_server.clip_query() runs the full Essentia analysis
    (Sound, instruments, mood, rhythm) exactly as the booth demo's tab capture does, then the audio is deleted;
  * start from a pool song: its stored numbers (results/<key>.npz).
Then recommend_song.recommend_query() ranks the pool: rescaled Sound cosine over the whole song, 3 parts and every
~30 s stretch, plus the chosen features (top 35% each) and the language filter.

The pool is Ryan's demo bundle (numbers only, no audio), kept in a private Hugging Face dataset and downloaded at
startup with a read-only token (Space secret HF_DATA_TOKEN). Only results/, the pool lists and the two AI lists are
unpacked from it; nothing in it is executed.

    GET  /api/health                        always 200 (the pool may still be loading)
    GET  /api/status                        {ready, pool, error}
    GET  /api/search?q=                     up to 8 pool songs
    GET  /api/samples                       one well-known song from each of the six biggest style groups
    POST /api/recommend                     {key, features, languages}            free
    POST /api/clip  (multipart: audio)      analyse a clip and recommend           [analyse]
    POST /api/refine                        {token, features, languages}           re-rank a clip's result, free
"""
import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # the student's modules live in the repository root

import demo_server  # noqa: E402  (helpers only: shape, build_heard, auto_samples, yt_id_of, messages, limits)
from api.rate_limit import check_rate_limit  # noqa: E402

DATA_REPO = os.environ.get("GROOVY_DATA_REPO", "smubiainfrastructure/ail-ay2627-s1-ryan-groovyeverywhere-data")
DATA_FILE = os.environ.get("GROOVY_DATA_FILE", "groovy-demo-bundle.zip")
K = 6                                # songs per list, as on the booth page
MAX_UPLOAD = 15 * 1024 * 1024        # bytes
CLIP_SECONDS = 60                    # only the first minute of an upload is analysed (the booth's captures are 30 s)
KEEP_RESULTS = 300                   # clip results kept for chip changes
SEARCH_LIMIT = 8
# Bundle members that may be unpacked: the numbers and lists the recommender reads. Anything else is ignored.
ALLOWED = re.compile(r"^(results/[A-Za-z0-9_.\-]+\.(npz|csv)|results/meta/[A-Za-z0-9_.\-]+\.json|pool_[a-z_]+\.csv|ai_(keep|block)\.txt)$")

state = {"ready": False, "pool": 0, "error": "", "stage": "starting"}
analysis_lock = threading.Lock()     # one Essentia analysis at a time (2 vCPUs)
results = collections.OrderedDict()  # token -> (query, meta) for /api/refine
results_lock = threading.Lock()
INSTRUMENTS: list[str] = []


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """The Hub answers a file request with a redirect to its CDN (a signed URL): send the token to the Hub only."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new.remove_header("Authorization")
        return new


def download(url, token, dest):
    """Plain streaming GET of one dataset file (huggingface_hub's downloader failed inside the Space on its HEAD check)."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    opener = urllib.request.build_opener(_DropAuthOnRedirect)
    try:
        with opener.open(req, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except urllib.error.HTTPError as e:  # the status only: never the URL's query string or headers
        raise RuntimeError(f"the pool bundle could not be downloaded (HTTP {e.code})") from None


def fetch_bundle():
    """Downloads the bundle zip from the private dataset and unpacks the allowed members into the repo root."""
    if os.path.exists(os.path.join(ROOT, "results", "index.csv")):
        return  # already unpacked (a restart of the same container, or local development)
    token = os.environ.pop("HF_DATA_TOKEN", "") or os.environ.pop("HF_TOKEN", "") or None
    tmp = tempfile.mkdtemp(prefix="groovy_bundle_")
    try:
        path = os.path.join(tmp, "bundle.zip")
        download(f"https://huggingface.co/datasets/{DATA_REPO}/resolve/main/{DATA_FILE}", token, path)
        with zipfile.ZipFile(path) as z:
            members = [m for m in z.namelist() if ALLOWED.match(m)]
            for m in members:
                z.extract(m, ROOT)
        print(f"bundle: {len(members)} files unpacked", flush=True)
    finally:
        token = None
        shutil.rmtree(tmp, ignore_errors=True)


def warm():
    """What the booth demo does before it opens: fetch the numbers, build the pool, load the ~30 s stretch index."""
    global INSTRUMENTS
    t0 = time.time()
    try:
        state["stage"] = "downloading the song pool"
        fetch_bundle()
        state["stage"] = "loading the song pool"
        import blind_test as bt
        import match
        state["pool"] = len(bt.pool()["key"])
        state["stage"] = "loading the ~30 s stretch index"
        match.windows()
        match.windows(False)
        try:
            import models
            INSTRUMENTS = [c.lower().replace(" ", "").replace("_", "") for c in models.classes("instruments")]
        except Exception:
            INSTRUMENTS = []
        state["ready"], state["stage"] = True, "ready"
        print(f"ready: {state['pool']} pool songs in {time.time() - t0:.0f}s", flush=True)
    except BaseException as e:  # keep serving /api/health and report the problem on /api/status
        state["error"], state["stage"] = f"{type(e).__name__}: {str(e)[:200]}", "failed"
        print(f"!! warm-up failed: {state['error']}", flush=True)


app = FastAPI(title="groovyeverywhere demo API", docs_url=None, redoc_url=None)
origins = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],  # no CORS_ORIGINS (local dev) -> any origin
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def start_warm():
    threading.Thread(target=warm, daemon=True).start()


def need_ready():
    if not state["ready"]:
        raise HTTPException(423, state["error"] or "The song pool is still loading. Try again in a minute.")


def pool():
    import blind_test as bt
    return bt.pool()


def song(i):
    P = pool()
    return dict(key=P["key"][i], title=P["title"][i], artist=P["artist_name"][i],
                yt=demo_server.yt_id_of(P["link"][i]), link=P["link"][i])


def heard(q):
    try:
        return demo_server.build_heard(q, INSTRUMENTS) if INSTRUMENTS else {}
    except Exception:  # the strip is a bonus: never let it break a result
        return {}


def lists(q, meta, features, languages):
    import blind_test as bt
    import recommend_song
    feats = [f for f in features if f in demo_server.VALID_FEATURES]
    langs = [lang for lang in languages if lang in demo_server.VALID_LANGUAGES]
    if not feats or not langs:
        raise HTTPException(400, "Choose at least one feature and one language.")
    res = demo_server.shape(recommend_song.recommend_query(q, meta, K, "+".join(feats), languages=langs), K)
    bs = res.get("best_sound")
    warning = ""
    if bs is not None and bs < bt.WEAK_COSINE:
        warning = demo_server.CAPTURE_MSG if not meta else demo_server.POOL_MSG
    return res, warning


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/status")
def status():
    return {"ready": state["ready"], "pool": state["pool"], "stage": state["stage"], "error": state["error"]}


@app.get("/api/search")
def search(q: str = Query("", max_length=100)):
    need_ready()
    words = q.lower().split()
    if not words:
        return {"songs": []}
    P = pool()
    hits = [i for i, (t, a) in enumerate(zip(P["title"], P["artist_name"])) if all(w in f"{t} {a}".lower() for w in words)]
    hits.sort(key=lambda i: -(P["listens"][i] if P["listens"][i] == P["listens"][i] else -1))  # best known first
    return {"songs": [song(i) for i in hits[:SEARCH_LIMIT]]}


@app.get("/api/samples")
def samples():
    need_ready()
    P = pool()
    picks = demo_server.auto_samples(P["key"], P["title"], P["artist_name"], P["group"], P["listens"])
    index = {k: i for i, k in enumerate(P["key"])}
    return {"songs": [song(index[s["key"]]) for s in picks]}


class RecommendBody(BaseModel):
    key: str = Field(max_length=40)
    features: list[str] = Field(default_factory=lambda: list(demo_server.VALID_FEATURES), max_length=3)
    languages: list[str] = Field(default_factory=lambda: list(demo_server.DEFAULT_LANGUAGES), max_length=5)


@app.post("/api/recommend")
def recommend(body: RecommendBody):
    """A pool song as the starting song: its stored numbers, as the booth demo's sample buttons do."""
    need_ready()
    import blind_test as bt
    from results_index import RES, read_meta
    P = pool()
    if body.key not in set(P["key"]):
        raise HTTPException(404, "That song isn't in the pool.")
    with np.load(os.path.join(RES, f"{body.key}.npz"), allow_pickle=False) as d:
        q = bt.query_from_analysis(dict(d))
    res, warning = lists(q, read_meta(body.key) or {}, body.features, body.languages)
    i = P["key"].index(body.key)
    return {"input": dict(song(i), kind="pool"), "heard": heard(q), "results": res, "warning": warning}


def to_wav(src, dst):
    """Any browser recording or audio file -> 16-bit mono 44.1 kHz WAV of at most CLIP_SECONDS (the format the
    booth's capture page sends, so capture_server.even_out_volume() can level it)."""
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-t", str(CLIP_SECONDS),
                        "-vn", "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", dst], capture_output=True, timeout=120)
    if p.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 44 + 44100 * 2 * 3:
        raise HTTPException(400, "That file couldn't be read as audio, or it is shorter than 3 seconds.")


@app.post("/api/clip")
def clip(request: Request, audio: UploadFile = File(...), features: str = Form("mood+rhythm+instruments"),
         languages: str = Form("+".join(demo_server.DEFAULT_LANGUAGES))):
    """Bring a song: analyse an uploaded or recorded clip with the student's models, then recommend."""
    need_ready()
    data = audio.file.read(MAX_UPLOAD + 1)
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Send an audio clip of up to 15 MB (about a minute is plenty).")
    if analysis_lock.locked():
        raise HTTPException(423, "Another visitor's song is being analysed. Try again in a few seconds.")
    import blind_test as bt
    import capture_server
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="hg_clip_") as d:  # the audio is deleted when this block ends
        src, wav = os.path.join(d, "upload"), os.path.join(d, "clip.wav")
        with open(src, "wb") as f:
            f.write(data)
        del data
        to_wav(src, wav)  # a file that isn't audio is rejected here, before it counts
        check_rate_limit(request, "analyse")  # after the cheap checks, right before the models run
        with analysis_lock:
            sig, feats = capture_server.clip_query(wav)
    if feats is None:
        raise HTTPException(422, "The recording was (almost) silent. Play the song louder or closer to the microphone.")
    q = bt.query_from_analysis(feats)
    res, warning = lists(q, {}, features.split("+"), languages.split("+"))
    token = uuid.uuid4().hex
    with results_lock:
        results[token] = q
        while len(results) > KEEP_RESULTS:
            results.popitem(last=False)
    seconds = round(time.time() - t0, 1)
    return {"token": token, "input": dict(kind="clip", title="your song", artist="", seconds=seconds), "heard": heard(q),
            "results": res, "warning": warning}


class RefineBody(BaseModel):
    token: str = Field(max_length=40)
    features: list[str] = Field(max_length=3)
    languages: list[str] = Field(max_length=5)


@app.post("/api/refine")
def refine(body: RefineBody):
    """Other features or languages for a clip already analysed: re-ranks the stored numbers, no new analysis."""
    need_ready()
    with results_lock:
        q = results.get(body.token)
    if q is None:
        raise HTTPException(410, "This result has expired. Bring the song again.")
    res, warning = lists(q, {}, body.features, body.languages)
    return {"results": res, "warning": warning}


@app.get("/")
def root():
    return {"service": "groovyeverywhere demo API", "health": "/api/health"}
