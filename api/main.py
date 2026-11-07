"""groovyeverywhere demo API (Cloud Run). API only: the page is on Vercel (web/).

Pick a song from the pool and get the two lists the booth demo shows: "closest in sound" and "sound, plus what you
care about" (mood / rhythm / instruments, every chosen feature in the top 35%), filtered by language. The ranking is
the student's own code, unchanged: recommend_song.recommend_query with blind_test, scoring and match. This module
only loads the pool from the slim data files (api/export_pool.py) instead of the booth machine's results/ folder.
No model runs at serve time (the songs were analysed offline with Essentia) and no audio is involved.

    GET  /api/health
    GET  /api/status                        {ready, pool}
    GET  /api/search?q=<title or artist>    up to 8 pool songs
    GET  /api/samples                       one well-known song from each of the six biggest style groups
    POST /api/recommend                     {key, features: [...], languages: [...]}
"""
import json
import os
import sys
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # the student's modules live in the repository root

import blind_test as bt  # noqa: E402
import demo_server  # noqa: E402  (helpers only: shape, mood_label, tempo_text, auto_samples, yt_id_of)
import match  # noqa: E402
import recommend_song  # noqa: E402
import scoring  # noqa: E402

DATA = os.environ.get("GROOVY_DATA_DIR") or os.path.join(ROOT, "api", "data")
K = 6  # songs per list, as on the booth page
SEARCH_LIMIT = 8


def load_pool():
    """Builds the dict blind_test.pool() returns, from pool.npz + pool.json, and installs it (and the Sound scale) as
    the student's module caches so recommend_query reads it. The ~30 s stretch vectors are not shipped (see the
    README): their result for each starting song is precomputed (stretch_*.npy), and window_sound() reads that row."""
    t0 = time.time()
    with open(os.path.join(DATA, "pool.json"), encoding="utf-8") as f:
        text = json.load(f)
    P = {k: v for k, v in text.items() if k != "meta"}
    with np.load(os.path.join(DATA, "pool.npz"), allow_pickle=False) as d:
        for k in ("whole", "parts", "inst", "inst_parts", "va_vg", "va_mc", "va_mc_parts", "listens",
                  "bpm", "confidence", "steadiness", "busyness"):
            P[k] = d[k].astype(np.float32)
        scale = (d["scale_mu"], d["scale_sd"])
    P["from"] = "files"
    match.use_scale_sources(bt.POOL_SOURCES)  # as blind_test.pool() does, before anything is rescaled
    match._scale[match._scale_sources] = scale
    P["scale"] = scale
    P["whole_z"] = scoring.scale_sound(P["whole"], scale).astype(np.float32)
    P["parts_z"] = scoring.scale_sound(P["parts"], scale).astype(np.float32)
    P = bt._finish(P)
    bt._pool = P
    match._win_error = "the ~30 s stretch vectors are not part of the hosted demo (see stretch_sound)"
    print(f"pool: {len(P['key'])} songs loaded in {time.time() - t0:.1f}s (mood model: {P['mood_kind']})", flush=True)
    return P, text["meta"]


POOL, META = load_pool()
STRETCH = {scaled: np.load(os.path.join(DATA, f"stretch_{'scaled' if scaled else 'plain'}.npy"), mmap_mode="r")
           for scaled in (True, False)}


def stretch_sound(q, P, scaled=True):
    """blind_test.window_sound() for a pool song: its best ~30 s stretch similarity to every pool song, read from the
    table api/export_pool.py made with the student's own match.windows() (int16 / 32767; -32768 = no stretch = -2)."""
    row = q.get("_row")
    if row is None:
        return None
    r = np.asarray(STRETCH[scaled][row])
    return np.where(r == -32768, -2.0, r / 32767.0).astype(np.float32)


bt.window_sound = stretch_sound  # recommend_query() and blind_test.raw_sound() call it through the module
INDEX = {k: i for i, k in enumerate(POOL["key"])}
SEARCH_TEXT = [f"{t} {a}".lower() for t, a in zip(POOL["title"], POOL["artist_name"])]

app = FastAPI(title="groovyeverywhere demo API", docs_url=None, redoc_url=None)
origins = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],  # no CORS_ORIGINS (local dev) -> any origin
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def song(i):
    return dict(key=POOL["key"][i], title=POOL["title"][i], artist=POOL["artist_name"][i],
                yt=demo_server.yt_id_of(POOL["link"][i]), link=POOL["link"][i])


def query_of(i):
    """blind_test.query_from_analysis() for a pool song, from the same numbers (rhythm is already finite in the pool)."""
    return dict(_row=i, whole=POOL["whole"][i].astype(np.float64), va_vg=POOL["va_vg"][i].astype(np.float64),
                va_mc=POOL["va_mc"][i].astype(np.float64), inst=POOL["inst"][i].astype(np.float64),
                **{f: float(POOL[f][i]) for f in ("bpm", "confidence", "steadiness", "busyness")})


def heard(q):
    """The booth page's "what we heard" strip, without instrument names (the model's class list is not shipped)."""
    v, a = q["va_vg"]
    if v != v or a != a:
        v, a = q["va_mc"]
    return dict(mood=demo_server.mood_label(float(v), float(a)), happiness=round(float(v), 1), energy=round(float(a), 1),
                tempo=demo_server.tempo_text(q["bpm"], q["confidence"]), instruments=[])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/status")
def status():
    return {"ready": True, "pool": len(POOL["key"])}


@app.get("/api/search")
def search(q: str = Query("", max_length=100)):
    words = q.lower().split()
    if not words:
        return {"songs": []}
    hits = [i for i, t in enumerate(SEARCH_TEXT) if all(w in t for w in words)]
    hits.sort(key=lambda i: -(POOL["listens"][i] if POOL["listens"][i] == POOL["listens"][i] else -1))  # best known first
    return {"songs": [song(i) for i in hits[:SEARCH_LIMIT]]}


@app.get("/api/samples")
def samples():
    picks = demo_server.auto_samples(POOL["key"], POOL["title"], POOL["artist_name"], POOL["group"], POOL["listens"])
    return {"songs": [song(INDEX[s["key"]]) for s in picks]}


class RecommendBody(BaseModel):
    key: str = Field(max_length=40)
    features: list[str] = Field(default_factory=lambda: list(demo_server.VALID_FEATURES), max_length=3)
    languages: list[str] = Field(default_factory=lambda: list(demo_server.DEFAULT_LANGUAGES), max_length=5)


@app.post("/api/recommend")
def recommend(body: RecommendBody):
    i = INDEX.get(body.key)
    if i is None:
        raise HTTPException(404, "That song isn't in the pool.")
    feats = [f for f in body.features if f in demo_server.VALID_FEATURES]
    langs = [lang for lang in body.languages if lang in demo_server.VALID_LANGUAGES]
    if not feats or not langs:
        raise HTTPException(400, "Choose at least one feature and one language.")
    q = query_of(i)
    res = recommend_song.recommend_query(q, META[i] or {}, K, "+".join(feats), languages=langs)
    return {"input": dict(song(i), heard=heard(q)), "results": demo_server.shape(res, K)}


@app.get("/")
def root():
    return {"service": "groovyeverywhere demo API", "health": "/api/health"}
