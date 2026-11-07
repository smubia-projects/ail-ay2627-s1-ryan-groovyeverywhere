"""Export the demo pool from Ryan's demo bundle into the API's slim data files (run once, offline).

    python api/export_pool.py <folder with the repo's .py files, the bundle's pool lists and results/> <out dir>

It runs the student's own blind_test.pool() on the bundle (the pool lists minus i_agree = n, YouTube only, AI-tagged
songs, ai_block.txt channels and dead links removed, ai_keep.txt winning), so the API serves exactly the songs the live
booth demo recommends from, then writes what recommend_song.recommend_query reads for those songs:

  pool.npz     numbers only (loads with allow_pickle=False):
               whole (N,1280) and parts (N,3,1280) Sound, float16; scale_mu / scale_sd (1280,) float64, the bundle's
               Sound rescaling; inst (N,40), inst_parts (N,3,40), va_vg, va_mc (N,2), va_mc_parts (N,3,2), listens,
               bpm, confidence, steadiness, busyness (N,), float32
  pool.json    text: key, artist (lower-case), artist_name, group, title, link, source, ai, and the starting-song
               details (title, artist, aliases) from results/meta/<key>.json
  song_languages.csv   the language label of each pool song (results/song_languages.csv, pool rows only)
  stretch_scaled.npy, stretch_plain.npy   (N,N) int16: row i = what blind_test.window_sound() returns when pool song i
               is the starting song (its best ~30 s stretch similarity to every pool song), rescaled and plain cosine,
               times 32767; -32768 = no stretch (window_sound's -2). Read with mmap, one row per request.

Left out (see the README): the ~30 s stretch vectors themselves (results/windows_cache.npz, 113,371 x 1,280, 278 MB):
the hosted demo only starts from pool songs, so their best-stretch scores are computed here once, with the student's
own match.windows(). Also left out: per-song files, the link-check and AI-tag tables (already applied by pool()), and
every song outside the pool.
"""
import csv
import json
import os
import sys

work, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, work)
import numpy as np  # noqa: E402
import blind_test as bt  # noqa: E402
import results_index  # noqa: E402
import song_languages  # noqa: E402

P = bt.pool()
n = len(P["key"])
os.makedirs(out, exist_ok=True)

f16 = lambda a: np.asarray(a, np.float64).astype(np.float16)  # noqa: E731
f32 = lambda a: np.asarray(a, np.float64).astype(np.float32)  # noqa: E731
mu, sd = P["scale"]
np.savez_compressed(
    os.path.join(out, "pool.npz"),
    whole=f16(P["whole"]), parts=f16(P["parts"]),
    scale_mu=np.asarray(mu, np.float64), scale_sd=np.asarray(sd, np.float64),
    inst=f32(P["inst"]), inst_parts=f32(P["inst_parts"]),
    va_vg=f32(P["va_vg"]), va_mc=f32(P["va_mc"]), va_mc_parts=f32(P["va_mc_parts"]),
    listens=f32(P["listens"]),
    **{k: f32(P[k]) for k in ("bpm", "confidence", "steadiness", "busyness")},
)

meta = []
for k in P["key"]:
    m = results_index.read_meta(k) or {}
    meta.append({x: m[x] for x in ("title", "artist", "aliases") if m.get(x)})
text = {f: list(P[f]) for f in ("key", "artist", "artist_name", "group", "title", "link", "source", "ai")}
text["meta"] = meta
with open(os.path.join(out, "pool.json"), "w", encoding="utf-8") as f:
    json.dump(text, f, ensure_ascii=False, separators=(",", ":"))

labels = song_languages.load()
with open(os.path.join(out, "song_languages.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["key", "language"])
    for k in P["key"]:
        if k in labels:
            w.writerow([k, labels[k]])

import match  # noqa: E402
import scoring  # noqa: E402

lib_keys = list(match.library()[0])
libpos = {k: j for j, k in enumerate(lib_keys)}
pos = np.array([libpos.get(k, -1) for k in P["key"]])
for scaled, name in ((True, "stretch_scaled.npy"), (False, "stretch_plain.npy")):
    owner, vecs = match.windows(scaled)
    order = np.argsort(owner, kind="stable")
    owner, vecs = owner[order], vecs[order]
    starts = np.r_[0, np.flatnonzero(np.diff(owner)) + 1]
    has = owner[starts]
    M = np.lib.format.open_memmap(os.path.join(out, name), mode="w+", dtype=np.int16, shape=(n, n))
    for b in range(0, n, 256):
        rows = range(b, min(n, b + 256))
        C = scoring.scale_sound(P["whole"][list(rows)], P["scale"] if scaled else None).astype(np.float32)  # as window_sound()
        C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-9
        S = C @ vecs.T
        best_lib = np.full((len(rows), len(lib_keys)), -2.0, np.float32)
        best_lib[:, has] = np.maximum.reduceat(S, starts, axis=1)
        best = np.where(pos >= 0, best_lib[:, np.maximum(pos, 0)], -2.0)
        M[b:b + len(rows)] = np.where(best <= -1.5, -32768, np.round(np.clip(best, -1, 1) * 32767)).astype(np.int16)
    M.flush()
    del M
    print(f"  {name}: best ~30 s stretch of {len(has)} songs, {len(owner)} stretches")

print(f"exported {n} pool songs; mood model: {P['mood_kind']}")
for name in ("pool.npz", "pool.json", "song_languages.csv", "stretch_scaled.npy", "stretch_plain.npy"):
    print(f"  {name}: {os.path.getsize(os.path.join(out, name)) / 1e6:.1f} MB")
