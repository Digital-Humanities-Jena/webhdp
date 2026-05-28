from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Metrics
ACTIVE_CONNECTIONS = Gauge(
    "hpc_link_active_connections",
    "Number of active SSH connections to HPC"
)

TRANSFER_THROUGHPUT = Counter(
    "hpc_link_transfer_bytes_total",
    "Total bytes transferred (upload/download)",
    ["direction"]
)

JOB_SUBMISSIONS = Counter(
    "hpc_link_job_submissions_total",
    "Total number of jobs submitted",
    ["status"] # success, failure
)
