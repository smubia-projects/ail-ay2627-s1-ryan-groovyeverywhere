# groovyeverywhere demo API (Cloud Run). Build context = repo root; .dockerignore keeps only api/ and the student's
# recommender modules. The page (web/) is on Vercel. No Essentia, TensorFlow or yt-dlp: the songs were analysed
# offline, and this image only ranks the stored numbers.
# python:3.13 rather than the playbook's 3.11: the student's code targets Python 3.14 (its Essentia build) and was
# tested here on 3.13.
FROM python:3.13-slim

WORKDIR /app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# The pool data (made by api/export_pool.py from Ryan's demo bundle) is a GitHub release asset, checked by SHA-256.
ARG DATA_URL=https://github.com/smubia-projects/ail-ay2627-s1-ryan-groovyeverywhere/releases/download/demo-data-v1
COPY api/fetch_data.py api/fetch_data.py
RUN python api/fetch_data.py "$DATA_URL" \
      pool.npz=f11b6f87c7cb5eb3bb371f4664df7e29629cf173f8059c235879bca06dbafb74 \
      pool.json=ed3993e6ce2e6eaeec56253bc5f1905d0f75f8df7b6bfe9a84e8aabe64d251aa \
      song_languages.csv=84f7462193f556278b3f2a4bf3b65b329cb090da2af536d70c33e8d71dee19ec \
      stretch_scaled.npy=3a95775f0116b697c2f274e9c5973e4b2b0dcaec273ddf0d3f6146368342f883 \
      stretch_plain.npy=c2f76a6fd378b2c93bfcaddb04000fabdbf027e5ab61dc7c84a523d8dd089b13 \
    && mkdir -p results && mv api/data/song_languages.csv results/song_languages.csv

COPY blind_test.py demo_server.py match.py recommend_song.py results_index.py scoring.py song_languages.py ./
COPY api/main.py api/main.py

RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health', timeout=5)" || exit 1

CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}
