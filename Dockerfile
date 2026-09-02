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
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .

# Kalan proje dosyalari
COPY config ./config

# Varsayilan: zamanlanmis surekli calisma
CMD ["finorch", "run"]
