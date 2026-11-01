#!/bin/sh
# scripts/stage-release.sh DIR: copy the files of a release into DIR, the
# directory the release workflow audits, records and zips. Edit RELEASE_FILES
# to match the repository; everything listed here ships, nothing else does.
set -eu
dest="${1:?usage: stage-release.sh DIR}"
RELEASE_FILES="*.owl *.ttl audit.yaml README.md CHANGELOG.md LICENSE NOTICE CITATION.cff"
RELEASE_DIRS="src/shapes src/examples src/sparql docs"
rm -rf "$dest"
mkdir -p "$dest"
for f in $RELEASE_FILES; do
  [ -f "$f" ] && cp "$f" "$dest/"
done
for d in $RELEASE_DIRS; do
  [ -d "$d" ] && mkdir -p "$dest/$d" && cp -R "$d/." "$dest/$d/"
done
echo "staged $(find "$dest" -type f | wc -l) file(s) in $dest"
