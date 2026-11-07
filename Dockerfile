# groovyeverywhere demo API (Hugging Face Space, Docker SDK, port 8080). The page (web/) is on Vercel.
# FastAPI around the student's own code: Essentia analysis of a visitor's clip (analyze.py, capture_server.py) and
# the recommender (blind_test.py, scoring.py, match.py, recommend_song.py). Python 3.14: the pinned
# essentia-tensorflow build only has Python 3.14 wheels (see ../requirements.txt).
FROM python:3.14-slim

WORKDIR /app

# ffmpeg turns browser recordings (webm/ogg/mp4) and uploads into the 16-bit WAV the student's capture path expects.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# The Essentia models (Music Technology Group, UPF; CC BY-NC-SA 4.0), baked into the image by the student's own
# downloader so a cold start reads them from disk.
COPY models.py ./
RUN python models.py

COPY analyze.py blind_test.py capture_server.py demo_server.py evaluate.py match.py pool_db.py recommend_song.py \
     results_index.py scoring.py song_languages.py tag_ai.py ./
COPY api/ api/

# The pool (Ryan's demo bundle, numbers only) is downloaded from a private dataset at startup into results/.
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser
ENV PYTHONUNBUFFERED=1 HF_HOME=/tmp/hf

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health', timeout=5)" || exit 1

CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}
