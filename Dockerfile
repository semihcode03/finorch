FROM python:3.11-slim

# ffmpeg: yt-dlp ses cikarimi ve faster-whisper icin gerekli
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Kurumsal SSL denetimi (self-signed CA) ardindaki aglar icin pip guvenilir hostlari
    PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org"

WORKDIR /app

# Once bagimliliklar (katman onbellegi icin)
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

# Kurumsal SSL denetimi: bazi aglar (or. Trend Micro Web Security) TLS trafigini
# kendi kok CA'si ile yeniden imzalar. certs/*.crt hem OS deposuna hem certifi
# paketine eklenir; httpx/openai/yt-dlp certifi kullandigi icin ikisi de gerekli.
# certs/ dizini yoksa adim atlanir (.dockerignore her zaman eslesmeyi garantiler).
COPY .dockerignore certs*/* /tmp/corp-certs/
RUN set -eu; \
    if ls /tmp/corp-certs/*.crt >/dev/null 2>&1; then \
        cp /tmp/corp-certs/*.crt /usr/local/share/ca-certificates/; \
        update-ca-certificates; \
        cat /tmp/corp-certs/*.crt >> "$(python -c 'import certifi; print(certifi.where())')"; \
    fi; \
    rm -rf /tmp/corp-certs

# Kalan proje dosyalari
COPY config ./config

# Varsayilan: zamanlanmis surekli calisma
CMD ["finorch", "run"]
