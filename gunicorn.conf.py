bind = "0.0.0.0:5000"
# gthread instead of sync: with 2 sync workers, two slow reasoner requests
# (600s timeout) froze the entire site for everyone else. Threads keep cheap
# requests flowing while reasoners run in subprocesses (robot/prover9/java).
workers = 2
worker_class = "gthread"
threads = 4
timeout = 600        # OWL reasoners can be slow
keepalive = 5
max_requests = 500
max_requests_jitter = 50
preload_app = True


def post_fork(server, worker):
    # preload_app forks workers after the app module has run db.create_all(),
    # so pooled DB connections exist in the master and are inherited as shared
    # sockets by every worker — concurrent use corrupts the wire protocol
    # (psycopg2 "PGRES_TUPLES_OK and no message"). Give each worker a fresh pool.
    try:
        from app import app, db
        with app.app_context():
            db.engine.dispose()
    except Exception:
        pass
accesslog = "-"
errorlog = "-"
loglevel = "info"
