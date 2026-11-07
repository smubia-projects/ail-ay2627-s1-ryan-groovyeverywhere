# groovyeverywhere

Tell it a song you love; it listens to the song and finds songs in a pool of about 9,000 that really sound like it, not just the ones everyone has heard.
Built for the AI Lodge Hackathon (October 2026), track: Projects for Daily Life.

* **Try it:** https://ryrxiaopang.github.io/groovyeverywhere/ (forwards to the live demo, which runs on our own computer; one song at a time)
* **Demo video:** https://www.youtube.com/watch?v=jMhueRJbihI
* **Write-up:** [`DEVPOST_STORY.md`](DEVPOST_STORY.md)

## AI Lodge hosted demo

The SMU BIA AI Lodge hosts an online version of groovyeverywhere at **https://ail-ay2627-s1-ryan-groovyeverywhere.vercel.app**, from the club's fork [`smubia-projects/ail-ay2627-s1-ryan-groovyeverywhere`](https://github.com/smubia-projects/ail-ay2627-s1-ryan-groovyeverywhere).

* **What it does:** search the pool (or pick a sample), choose a song, and get the two lists the booth demo shows: closest in sound, and sound plus the mood, rhythm and instruments you pick (every chosen feature in the top 35%), with the language chips. The ranking is this repository's own `recommend_song.recommend_query`, unchanged.
* **What it leaves out:** bringing your own song (YouTube download and live Essentia analysis), tab capture and the "would add / skip" answers. Those need the analysis models and run only on the booth laptop.
* **How:** [`api/`](api/main.py) is a small FastAPI service on Cloud Run; [`web/`](web/) is a static page on Vercel. No model runs at serve time and no audio is involved.
* **The data, trimmed from Ryan's demo bundle (512 MB, 17,896 files):** [`api/export_pool.py`](api/export_pool.py) runs `blind_test.pool()` on the bundle and keeps only what `recommend_query` reads for the 8,933 pool songs: Sound (whole song + 3 parts, float16), the Sound rescaling, instruments, mood, rhythm, titles, links, AI tags and language labels (91 MB + 2 MB). The 278 MB index of ~30 s stretches (113,371 x 1,280) is replaced by each pool song's best-stretch similarity to every other pool song, computed once with `match.windows()` (two 8,933 x 8,933 int16 tables, read one row per request). Per-song files, link checks and tag tables are dropped (already applied). On 40 random songs x 2 settings the hosted lists and numbers are identical to the full pipeline. The files are not in git (the project's rule): the image downloads them from a release and checks their SHA-256.
* **Licences:** the numbers come from Essentia models by the Music Technology Group (UPF), CC BY-NC-SA 4.0 (non-commercial, with credit); see [`NOTICE.md`](NOTICE.md).
* **Local run:** `pip install -r api/requirements.txt`, put the exported files in `api/data/` (and `song_languages.csv` in `results/`), `uvicorn api.main:app --port 8080`, then serve `web/` after `node web/build.js`.

## 1. Problem statement

Music recommendations tend to follow popularity: the more a song has been played, the more it gets pushed, and songs a listener would love get buried.
Most apps also recommend what *other listeners* of a song played, not songs that actually *sound* like it. So listeners who want "more like this one"
(the same mood, energy, instruments, feel) keep being sent the same well-known tracks. It is worth solving because finding new music is one of the most
common everyday uses of streaming apps, and it is also how smaller artists get heard. A new problem makes it harder: AI-generated uploads now flood the
least-played corners of YouTube, so a naive "less popular" recommender mostly recommends AI music (58% of the "sound only" picks in our first friends' test were tagged as AI-generated).

## 2. Solution overview

groovyeverywhere listens to the song itself. A visitor types a song name or pastes a YouTube link; the server downloads the audio into a temporary folder,
turns the whole song into numbers with open audio-AI models, deletes the audio, and compares the numbers with every song in its pool. It returns two lists:
**closest in sound**, and **sound plus what you care about** (mood, rhythm and / or instruments). Every match is ranked against the whole pool, the page
says what the models heard, and it warns when nothing in the pool is really close instead of presenting weak matches as good.

## 3. Key features

* **One box:** a song name (YouTube search, 5 candidates) or a YouTube link. Songs already stored are answered in 1-2 s (INSTANT badge); a new song takes about 20 s on our desktop.
* **Two lists:** closest in sound, and sound plus the features you pick (each chosen feature must reach the pool's 65th percentile).
* **"What we heard":** the mood in words, the tempo (only when the beat detector is sure) and the main instruments.
* **Honest numbers:** matches are shown as rankings ("closer than 99.4% of the pool", never "100% match"), and a weak-match warning when the best match is not close.
* **Language chips:** English, Chinese and Korean on by default; Japanese and other languages on request (sound alone ignores language: a Chinese rap song can sound like French rap).
* **Up to 3 songs per visitor**, each in its own tab with its own lists; songs are never blended (mixing styles averages the numbers and recommends muddy matches).
* **Tab-capture fallback:** if YouTube blocks a download, the page records 30 s of the song from another browser tab instead.
* **A pool of about 9,000 songs by 2,460 artists** aimed at younger listeners (about 6,100 English, 1,400 Chinese, 1,100 Korean, 300 Japanese), with AI-generated uploads removed.

## 4. AI integration

AI is the core of the system, and it is not an LLM wrapper: every recommendation comes from audio models listening to the song.

1. **Sound:** Discogs-EffNet (an audio neural network trained on millions of tracks) turns each song into 1,280 numbers, an *audio embedding*, much like a word embedding for text.
2. **Mood:** VGGish feeding an emoMusic model gives happiness and energy scores. **Instruments:** a classifier scores 40 instruments. **Rhythm:** tempo and steadiness from a beat tracker.
3. **Matching:** cosine similarity between Sound embeddings after a gentle rescaling fitted on the pool, $\tilde x = (x-\mu)/\sigma^{0.25}$; we compared several distance measures on validation songs before choosing this one (a full z-score failed our own style check). Each song is also compared stretch by stretch (every ~30 s window), so a song that is similar in one part is found.
4. **Combining features:** the best part of each song is chosen after combining features, and every chosen feature must reach the 65th percentile, so one strong feature cannot hide a bad one.
5. **AI-music detection:** a tagger reads each upload's title and description for signs of AI generation (Suno, "AI-generated", mood-mill patterns), plus a block list of AI channels.
6. **Language labels:** an offline language detector (Lingua) reads each song's own title, after the title's writing script and the search it came from.

## 5. External tools and datasets

| Tool / data | Used for |
|---|---|
| [Essentia](https://essentia.upf.edu/) and its [pretrained models](https://essentia.upf.edu/models.html) (Discogs-EffNet, VGGish, emoMusic, MTG-Jamendo instrument and mood classifiers) | all audio analysis (library AGPL-3.0, models CC BY-NC-SA 4.0) |
| [MTG-Jamendo dataset](https://github.com/MTG/mtg-jamendo-dataset) metadata (`data/`) | testing the models, including a sealed test split scored once |
| YouTube (through [yt-dlp](https://github.com/yt-dlp/yt-dlp), with [ffmpeg](https://ffmpeg.org/) and [deno](https://deno.com/)) and the YouTube Data API | the pool's songs and their details; visitors' songs (audio deleted after analysis) |
| Spotify and Deezer public artist pages | choosing which artists to put in the pool |
| [Lingua](https://github.com/pemistahl/lingua-py) | language labels (offline) |
| NumPy, Python's standard web server, HTML / CSS / JavaScript | the matching code and the website |
| Cloudflare Tunnel and GitHub Pages | the public link |
| Claude Code | coding assistant |

Full credits and licences: [`NOTICE.md`](NOTICE.md).

## 6. Installation and setup (Linux / WSL2, Python 3.14)

```bash
git clone https://github.com/ryrxiaopang/groovyeverywhere.git && cd groovyeverywhere
python3.14 -m venv .venv && source .venv/bin/activate                           # the pinned Essentia build installs on Python 3.14 only
pip install -r requirements.txt
sudo apt install -y ffmpeg && curl -fsSL https://deno.land/install.sh | sh     # yt-dlp needs deno for YouTube; open a new terminal afterwards
python models.py                                                              # downloads the Essentia models (about 60 MB)
python demo_server.py --fake      # practice mode: the page with canned matches, no pool needed -> http://localhost:8765
python demo_server.py --check     # pre-flight check for the real demo
python demo_server.py             # the real demo on http://localhost:8765 (needs the analysed pool in results/)
```

The analysed pool (`results/`, the `pool_*.csv` lists) is data and is not in this repository: build it with `build_youtube.py` / `build_from_spotify.py` and
`run_tests.py --list <list>`, or copy a bundle made with `make_demo_bundle.py`. `python synthetic_tests.py` is the offline self-check (32 sections; the first ones need Essentia).
`DEMO.md` is the full run sheet for the demo.

## 7. AI safety and limitations

**Guardrails built in**
* **Privacy: no audio is ever kept.** Every download goes into a temporary folder that is deleted straight after analysis; an offline test checks the deletion for every source, and a sweep removes folders left by a crash. Logs hold numbers, titles and an anonymous visitor id only (no IP addresses); the page tells visitors this.
* **Synthetic content:** AI-generated songs are removed from the pool by the tagger and the channel block list.
* **Safe inputs:** only an 11-character YouTube video id is ever used (the server rebuilds the address itself, so nothing else can be fetched); commands never go through a shell; request sizes are capped; live streams, premieres, videos over 10 minutes and non-songs are refused; one analysis runs at a time and at most 2 searches.
* **Honest output:** rankings instead of "% match", a weak-match warning, and the start song's own artist (under their channel, VEVO / Topic or label names) is never recommended back.

**Testing**

| What | Result |
|---|---|
| Sealed test: 1,143 songs of the official MTG-Jamendo test split, pass marks fixed before looking, scored once (6 Oct 2026) | 16 checks pass, 3 fail, 6 warn, 2 skipped ([`report_test.html`](report_test.html), [`evidence_summary_test.json`](evidence_summary_test.json)) |
| The 3 failures | Sound keeps two styles apart 65% of the time (bar 85%; only 5 songs in one of the styles); both beat-detection checks 64-67% (bar 85%) |
| Sound finds a song by the same artist from another album in its top 10 | 29% of questions (138 questions) |
| AI-music tagger, checked by listening to 99 songs | "confirmed" right 12 of 12, "likely" 28 of 29; finds about 77% of AI music (95% range 59-85%) |
| Singer-voice matching (dropped) | +2.8 points (95% range -5.1 to +10.8) against a +10 bar set before the run |
| Demo rehearsal on the desktop | 17 of 17 real songs worked after fixing a YouTube download problem (2 of 17 had failed with HTTP 403) |
| Offline self-check | 32 sections (deletion of audio, failure routes, odd requests, AI removal, language labels, ...) |
| Code reviews | two rounds of independent reviews (12 and 18 Oct); every finding was checked, fixed and given a test |

The first scoring run of the sealed test was defective (634 of 1,143 songs were read wrongly); it was fixed, disclosed and kept as `*_run1_defective.*`. The pass marks are in
[`archive/README_first_kit.md`](archive/README_first_kit.md); the frozen code fingerprint of the sealed run is [`test_split_freeze.json`](test_split_freeze.json); validation numbers are in [`report_validation.html`](report_validation.html).
(GitHub shows the `.html` reports as source: download them to read them.)

**Limitations**
* Rhythm is the weakest feature (beat-detection checks 64-67% against an 85% bar), so it is presented as optional.
* The AI tagger finds about 77% of AI music; the block list covers part of the rest, so some AI songs may remain.
* There is no scored listener test yet: the first friends' round was confounded by AI uploads, and the second was not scored (the ratings did not come back). Match rankings say how close a song sounds, not how much you will like it.
* The pool is about 9,000 songs, mostly pop, R&B, indie and Asian pop: metal, classical or Latin songs find few real neighbours (the page warns).
* Language labels are automatic: a few English songs are labelled "other" and hidden until that chip is turned on.
* The live demo runs on our own computer (the models are too large for free hosting, and YouTube blocks cloud servers), so the public link works only while that computer is on; YouTube can block some downloads (tab capture is the fallback).
* The Essentia models are CC BY-NC-SA: this is a non-commercial student project. The code is MIT ([`LICENSE`](LICENSE)).

## Main files

| | |
|---|---|
| `demo_server.py`, `demo.html` | the demo website (search, live analysis, results, language and feature chips, tab-capture fallback) |
| `analyze.py`, `models.py`, `sources.py` | one song to numbers; the models; temporary downloads that are always deleted |
| `recommend_song.py`, `blind_test.py`, `scoring.py`, `match.py` | matching, ranking and the friends' blind-test lists |
| `song_languages.py` | language labels for the language filter |
| `tag_ai.py`, `mark_ai_out.py`, `ai_channels.py`, `ai_tag_check.py` | AI-music detection, removal and its listening check |
| `build_from_spotify.py`, `deezer_discover.py`, `add_channel.py`, `add_song.py`, `boost_artists.sh` | growing the pool |
| `pool_summary.py`, `pool_duplicates.py`, `find_official_versions.py` | pool statistics and quality |
| `evaluate.py`, `SUCCESS_RULE.md` | the sealed test and the pre-registered success rule |
| `synthetic_tests.py` | the offline self-check |
| `DEMO.md`, `CLAUDE.md` | demo run sheet; full project notes |

The first test kit's README (160 songs, Jamendo / FMA / Audius) is kept in [`archive/README_first_kit.md`](archive/README_first_kit.md).
