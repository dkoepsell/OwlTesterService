FROM python:3.11-slim

# Install system dependencies:
#   default-jre-headless — Java runtime for OWL reasoners (Pellet/HermiT)
#   libpq-dev + gcc    — needed to build psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK corpora so the container doesn't phone home at runtime
RUN python -c "import nltk; nltk.download('wordnet'); nltk.download('omw-1.4')"

# Copy application code
COPY . .

# Uploads are stored on a mounted volume; create the dir as a fallback
RUN mkdir -p uploads

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]
