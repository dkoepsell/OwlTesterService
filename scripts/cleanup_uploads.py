"""Lightweight duplicate cleanup: direct psycopg2 + filesystem, no app import
(importing app pulls in owlready2/BFO and gets OOM-killed on the small host).
Dry-run by default; --execute to apply."""
import hashlib
import os
import sys

import psycopg2

EXECUTE = '--execute' in sys.argv
UPLOADS = '/app/uploads'


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

cur.execute("SELECT id, user_id, original_filename, file_path, file_size, "
            "upload_date FROM ontology_file ORDER BY upload_date ASC")
rows = cur.fetchall()
print(f"{len(rows)} ontology_file rows")

groups = {}
missing = []
for row in rows:
    id_, uid, oname, path, size, ts = row
    if not os.path.exists(path):
        missing.append(id_)
        continue
    groups.setdefault((uid, oname, md5(path)), []).append(row)

print(f"[1] {len(missing)} rows with missing files: {missing}")
if EXECUTE and missing:
    cur.execute("DELETE FROM ontology_analysis WHERE ontology_file_id = ANY(%s)",
                (missing,))
    cur.execute("DELETE FROM ontology_file WHERE id = ANY(%s)", (missing,))

dup_rows, dup_bytes = 0, 0
for key, members in groups.items():
    if len(members) < 2:
        continue
    keeper = members[-1]                       # newest (rows sorted by date)
    losers = members[:-1]
    loser_ids = [m[0] for m in losers]
    dup_rows += len(losers)
    dup_bytes += sum(m[4] or 0 for m in losers)
    print(f"    {key[1]}: keep {keeper[0]}, drop {loser_ids}")
    if EXECUTE:
        cur.execute("SELECT count(*) FROM ontology_analysis "
                    "WHERE ontology_file_id = %s", (keeper[0],))
        if cur.fetchone()[0] == 0:
            cur.execute("UPDATE ontology_analysis SET ontology_file_id = %s "
                        "WHERE id = (SELECT max(id) FROM ontology_analysis "
                        "WHERE ontology_file_id = ANY(%s))",
                        (keeper[0], loser_ids))
        cur.execute("DELETE FROM ontology_analysis "
                    "WHERE ontology_file_id = ANY(%s)", (loser_ids,))
        cur.execute("DELETE FROM ontology_file WHERE id = ANY(%s)", (loser_ids,))
        for m in losers:
            if os.path.exists(m[3]):
                os.remove(m[3])
print(f"[2] {dup_rows} duplicate rows, {dup_bytes / 1e6:.0f} MB")

import time
cur.execute("SELECT file_path FROM ontology_file")
referenced = {os.path.basename(p) for (p,) in cur.fetchall()}
# only files older than an hour: a just-uploaded file whose row committed
# after our snapshot must not be treated as stray
stray = [f for f in os.listdir(UPLOADS)
         if f not in referenced
         and os.path.isfile(os.path.join(UPLOADS, f))
         and time.time() - os.path.getmtime(os.path.join(UPLOADS, f)) > 3600]
print(f"[3] {len(stray)} stray files on disk")
if EXECUTE:
    for f in stray:
        os.remove(os.path.join(UPLOADS, f))

conn.commit()
print('APPLIED' if EXECUTE else 'DRY RUN')
