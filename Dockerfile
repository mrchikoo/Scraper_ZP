# Lead Outreach - Docker image (alternative to the Windows installer).
# Simple single-stage build: Python 3.11 + Debian's Chromium and chromedriver.
#
#   docker compose up -d --build      then open http://127.0.0.1:8765
#
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OUTREACH_DATA_DIR=/data \
    OUTREACH_HOST=0.0.0.0 \
    OUTREACH_PORT=8765 \
    OUTREACH_NO_BROWSER=1 \
    OUTREACH_IN_DOCKER=1 \
    OUTREACH_CHROME_BINARY=/usr/bin/chromium \
    OUTREACH_CHROMEDRIVER=/usr/bin/chromedriver \
    CHROME_BIN=/usr/bin/chromium \
    SE_OFFLINE=true

# Chromium + matching chromedriver from Debian (works on amd64 and arm64,
# so Selenium Manager never has to download anything inside the container).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-liberation ca-certificates tzdata tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/outreach

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

# Unprivileged user; /data is the only writable place it needs.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin outreach \
 && mkdir -p /data \
 && chown -R outreach:outreach /data
USER outreach

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import json,os,sys,urllib.request as u; r=u.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('OUTREACH_PORT','8765'), timeout=4); sys.exit(0 if json.load(r).get('ok') else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
