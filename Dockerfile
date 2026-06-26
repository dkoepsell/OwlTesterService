FROM python:3.11-slim

# Install system dependencies:
#   default-jre-headless — Java runtime for OWL reasoners (Pellet/HermiT) and ROBOT
#   libpq-dev + gcc    — needed to build psycopg2-binary
#   wget               — to fetch ROBOT during image build
#   prover9            — Prover9 + Mace4 for the FOL prover cross-check (SPEC Task 5);
#                        the cross-check degrades gracefully if this is absent
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    libpq-dev \
    gcc \
    wget \
    prover9 \
    && rm -rf /var/lib/apt/lists/*

# Install ROBOT (OBO/OWL toolkit) for external reasoning on large ontologies.
# Uses ELK by default — orders of magnitude faster than in-process owlready2/Pellet
# on EL-profile ontologies, and doesn't hang on anonymous restrictions.
ARG ROBOT_VERSION=1.9.6
RUN wget -q "https://github.com/ontodev/robot/releases/download/v${ROBOT_VERSION}/robot.jar" \
        -O /usr/local/bin/robot.jar && \
    printf '#!/bin/sh\nexec java -jar /usr/local/bin/robot.jar "$@"\n' > /usr/local/bin/robot && \
    chmod +x /usr/local/bin/robot && \
    robot --version

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK corpora so the container doesn't phone home at runtime
RUN python -c "import nltk; nltk.download('wordnet'); nltk.download('omw-1.4')"

# Copy application code (vendors bfo/bfo-2020.owl into the image; no runtime fetch)
COPY . .

# Sanity-check the vendored BFO bundle at build time: fail the build if the OWL
# is missing or the disjointness structure regressed below the SPEC acceptance.
RUN python -c "from bfo.catalog import load_catalog; c=load_catalog(); assert len(c.disjoint_pairs) > 7, 'BFO disjointness regressed'; print('BFO bundle OK:', len(c.disjoint_pairs), 'disjoint pairs')"

# Uploads are stored on a mounted volume; create the dir as a fallback
RUN mkdir -p uploads

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]
