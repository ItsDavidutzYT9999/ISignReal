"""Gunicorn configuration for iOS App Signer"""
import multiprocessing

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = min(4, multiprocessing.cpu_count())
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeout settings - critical for large file uploads
timeout = 600  # 10 minutes for large IPA files
keepalive = 30
graceful_timeout = 30

# Logging
loglevel = "info"
errorlog = "-"
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "ios-app-signer"

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = "/tmp"

# SSL (disabled for internal use)
keyfile = None
certfile = None

# Performance
preload_app = False
reuse_port = True

# Worker recycling
max_requests = 1000
max_requests_jitter = 50

# Memory and file limits
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190