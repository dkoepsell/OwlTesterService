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

# --- Builder stage: kindwork-core sidecar dependencies -------------------------
# The Kindwork module runs the vendored Kindwork page's generators in Node
# (kindwork_core/). Install its locked runtime deps here; the final image takes
# the node binary and node_modules only.
FROM node:20-slim AS kwnode
WORKDIR /kw
COPY kindwork_core/package.json kindwork_core/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

# --- CLI image: the audit toolchain only (SPEC-release.md, section 3) ---------
# For CI and the GitHub Action: Python, Java, ROBOT, owlready2 (HermiT), pyshacl,
# rdflib, PyYAML, the vendored BFO and the owltester package. No Flask, gunicorn,
# Node or Postgres client. Build it with --target cli; an untargeted build makes
# the web image below (the last stage).
#   docker build --target cli --build-arg OWLTESTER_VERSION=$(git rev-parse --short HEAD) \
#     -t owltester-cli .
#   docker run --rm -v "$PWD:/work" -w /work owltester-cli audit release.zip --fail-on major
FROM python:3.11-slim AS cli
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless wget \
    && rm -rf /var/lib/apt/lists/*
ARG ROBOT_VERSION=1.9.6
RUN wget -q "https://github.com/ontodev/robot/releases/download/v${ROBOT_VERSION}/robot.jar" \
        -O /usr/local/bin/robot.jar && \
    printf '#!/bin/sh\nexec java -jar /usr/local/bin/robot.jar "$@"\n' > /usr/local/bin/robot && \
    chmod +x /usr/local/bin/robot && robot --version && apt-get purge -y wget
WORKDIR /opt/owltester
COPY requirements-cli.txt .
RUN pip install --no-cache-dir -r requirements-cli.txt
COPY owltester/ owltester/
COPY bfo/ bfo/
COPY kindwork/ kindwork/
COPY shacl_tools.py bfo_lint.py ontology_bundle.py owl_format_detector.py ./
COPY scripts/check_bundled_jar_java.py scripts/
RUN python scripts/check_bundled_jar_java.py && \
    python -c "from bfo.catalog import load_catalog; assert len(load_catalog().disjoint_pairs) > 7"
ARG OWLTESTER_VERSION=
ENV OWLTESTER_VERSION=${OWLTESTER_VERSION} PYTHONPATH=/opt/owltester HOME=/tmp
RUN python -m owltester.cli --help >/dev/null && echo "owltester cli OK"
ENTRYPOINT ["python", "-m", "owltester.cli"]

# --- Final image --------------------------------------------------------------
FROM python:3.11-slim

# Install system dependencies:
#   default-jre-headless — Java runtime for OWL reasoners (Pellet/HermiT) and ROBOT
#   libpq-dev + gcc    — needed to build psycopg2-binary
#   wget               — to fetch ROBOT during image build
#   graphviz           — `dot` layout for the UML view (owl2uml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    graphviz \
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

# The commit this image was built from, shown as "Tool version" on audit reports.
# .git is not in the build context, so pass it in:
#   docker-compose build --build-arg OWLTESTER_VERSION=$(git rev-parse --short HEAD) app
# Without it, reports show src-<hash> of the audit code instead.
ARG OWLTESTER_VERSION=
ENV OWLTESTER_VERSION=${OWLTESTER_VERSION}

# Node runtime + deps for the kindwork-core sidecar; fail the build if it can't
# load the vendored Kindwork page.
COPY --from=kwnode /usr/local/bin/node /usr/local/bin/node
COPY --from=kwnode /kw/node_modules /app/kindwork_core/node_modules
RUN echo '{"op":"health"}' | node kindwork_core/bin/kindwork-core.mjs | grep -q '"ok":true' && \
    echo "kindwork-core OK"

# Sanity-check the vendored BFO bundle at build time: fail the build if the OWL
# is missing or the disjointness structure regressed below the SPEC acceptance.
RUN python -c "from bfo.catalog import load_catalog; c=load_catalog(); assert len(c.disjoint_pairs) > 7, 'BFO disjointness regressed'; print('BFO bundle OK:', len(c.disjoint_pairs), 'disjoint pairs')"

# Fail the build if owlready2's bundled Jena jars need a newer JRE than is
# installed (owlready2 >= 0.50 ships Java-25 jars that crash Pellet on Java 21).
# This catches a future owlready2 bump before it reaches a user's first upload.
RUN python scripts/check_bundled_jar_java.py

# Uploads are stored on a mounted volume; create the dir as a fallback
RUN mkdir -p uploads

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"]
