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
accesslog = "-"
errorlog = "-"
loglevel = "info"
