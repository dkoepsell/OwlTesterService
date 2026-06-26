# --- Builder stage: compile Prover9 + Mace4 (LADR) from source ----------------
# Debian dropped the prover9 package (no candidate in trixie), so we build LADR
# ourselves and copy just the two binaries into the final image. They power the
# FOL prover cross-check (SPEC Task 5); the cross-check degrades gracefully if
# absent, so a build failure here never breaks the app at runtime.
# laitep/ladr is a maintained mirror of McCune's LADR. The sed patch reorders
# -lm after the objects (modern ld is link-order sensitive; libm's round() would
# otherwise be unresolved), and the relaxed CFLAGS let the old C build under
# GCC 14's stricter defaults.
FROM python:3.11-slim AS ladr
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/laitep/ladr /tmp/ladr && \
    cd /tmp/ladr && \
    sed -i 's/-lm -o/-o/g; s#\.\./ladr/libladr.a#../ladr/libladr.a -lm#g' provers.src/Makefile && \
    make all CFLAGS="-O2 -w -fcommon -std=gnu89 -Wno-implicit-int -Wno-implicit-function-declaration -Wno-return-mismatch" && \
    test -x bin/prover9 && test -x bin/mace4

# --- Final image --------------------------------------------------------------
FROM python:3.11-slim

# Install system dependencies:
#   default-jre-headless — Java runtime for OWL reasoners (Pellet/HermiT) and ROBOT
#   libpq-dev + gcc    — needed to build psycopg2-binary
#   wget               — to fetch ROBOT during image build
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    libpq-dev \
    gcc \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Prover9 + Mace4 from the builder stage (dynamically link libc/libm, present in base).
COPY --from=ladr /tmp/ladr/bin/prover9 /tmp/ladr/bin/mace4 /usr/local/bin/
RUN prover9 --help >/dev/null 2>&1; mace4 --help >/dev/null 2>&1; echo "prover9/mace4 installed"

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
