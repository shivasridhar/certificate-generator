# Bulk Certificate Generator Backend

## 1. Overview
The Bulk Certificate Generator is an asynchronous backend service designed to process bulk certificate issuance requests reliably. It accepts event metadata alongside a list of recipient names and email addresses, validates recipient entries individually, and renders landscape A4 PDF certificates in the background using ReportLab. The service isolates individual failures so that invalid entries do not abort valid certificates, provides live job progress tracking, and allows clients to retrieve individual PDF certificates or export an entire batch as a ZIP archive.

## 2. Tech Stack
- **FastAPI**: Modern, high-performance web framework for building the REST API.
- **SQLAlchemy 2.x**: Object Relational Mapper for database modeling and transactional operations.
- **SQLite**: Default relational database engine (configured with thread safety, easily swapped to PostgreSQL via environment variable).
- **Pydantic v2**: Request schema validation, strict structural checks, and response serialization.
- **ReportLab**: Programmatic PDF document generation engine.
- **Pytest & HTTPX / TestClient**: Automated test suite and isolated in-memory test fixtures.

## 3. Setup

### Windows (PowerShell)
```powershell
# 1. Create a virtual environment using Python 3.11+
py -3.13 -m venv .venv

# 2. Activate the virtual environment
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

### macOS / Linux (Bash or Zsh)
```bash
# 1. Create a virtual environment using Python 3.11+
python3 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

## 4. Configuration
Configuration parameters are defined in `app/config.py` and read directly from environment variables. If an environment variable is not defined, the service falls back to its default value.

| Variable Name | Default Value | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///<project_root>/certificates.db` | SQLAlchemy connection string. Defaults to a local SQLite database file in the project root. For PostgreSQL in production, set to `postgresql+psycopg2://user:password@host:port/dbname`. |
| `OUTPUT_DIR` | `<project_root>/output` | Filesystem directory where generated PDF certificate files are stored. Parent directories are created automatically. |
| `MAX_RECIPIENTS_PER_JOB` | `1000` | Upper bound on the number of recipients accepted in a single bulk job payload. Structurally rejects larger batches with HTTP 422. |

An example environment file template is provided in `.env.example`.

## 5. Running the Application
Start the ASGI development server with Uvicorn:

```bash
uvicorn app.main:app --reload
```

The server binds to `http://127.0.0.1:8000` by default.
- Interactive OpenAPI documentation (Swagger UI): `http://127.0.0.1:8000/docs`
- Alternative API documentation (ReDoc): `http://127.0.0.1:8000/redoc`
- Health check probe: `http://127.0.0.1:8000/health`

## 6. Running Tests
Execute the full automated test suite with verbose output:

```bash
pytest -v
```

All 35 unit and integration tests run against an isolated in-memory SQLite database (`StaticPool`), ensuring fast and deterministic execution without touching the local disk.

### Note on Deprecation Warning
Running `pytest -W default` displays one third-party warning:
```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```
This warning originates internally within Starlette 1.7's `TestClient` module as it prepares for future `httpx2` support. It does not affect application functionality or test execution.

## 7. API Reference

### POST /jobs
- **Purpose**: Submits a new bulk certificate generation job. Validates structural payload integrity, runs recipient-level validation, creates initial database records, and queues background PDF generation.
- **Success Status**: `202 Accepted` (returns `JobOut` schema).
- **Error Statuses**:
  - `422 Unprocessable Entity`: Structurally invalid payload (missing `event_name`, missing `issuer`, invalid `issue_date`, empty `recipients` list, or `recipients` count exceeding `MAX_RECIPIENTS_PER_JOB`).

### GET /jobs/{job_id}
- **Purpose**: Retrieves complete metadata for a batch job, aggregate progress counters, completion percentage (`progress_percent`), and the full list of associated certificates with their individual statuses.
- **Success Status**: `200 OK` (returns `JobDetailOut` schema).
- **Error Statuses**:
  - `404 Not Found`: Job UUID does not exist.

### GET /jobs/{job_id}/certificates
- **Purpose**: Returns a paginated list of certificates for a specific job, ordered deterministically by `created_at ASC, id ASC`.
- **Query Parameters**:
  - `status` (*optional*): Filters by certificate status (`pending`, `success`, `failed`).
  - `limit` (*optional*, default: `100`, max: `500`): Maximum records to return.
  - `offset` (*optional*, default: `0`): Number of records to skip.
- **Success Status**: `200 OK` (returns `list[CertificateOut]`).
- **Error Statuses**:
  - `404 Not Found`: Job UUID does not exist.
  - `422 Unprocessable Entity`: Invalid query parameter value (e.g. unknown status enum or limit > 500).

### GET /certificates/{certificate_id}/download
- **Purpose**: Downloads a single generated certificate PDF file with `Content-Type: application/pdf`.
- **Success Status**: `200 OK`.
- **Error Statuses**:
  - `404 Not Found`: Certificate ID does not exist, or status is `success` but the file was deleted from disk.
  - `409 Conflict`: Certificate is in `pending` status ("Certificate is not ready yet"), or in `failed` status (includes the recorded error reason).

### GET /jobs/{job_id}/download
- **Purpose**: Streams all successfully generated certificate PDFs for a job compressed inside a single ZIP archive.
- **Success Status**: `200 OK` (`Content-Type: application/zip`).
- **Error Statuses**:
  - `404 Not Found`: Job UUID does not exist.
  - `409 Conflict`: Job has zero successfully generated certificates to download.

## 8. Usage Walkthrough

### Step 1: Submit a Mixed Bulk Job

#### cURL
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Cloud Native Masterclass",
    "issuer": "Engineering Academy",
    "issue_date": "2026-10-07",
    "recipients": [
      { "name": "Alice Johnson", "email": "alice@example.com" },
      { "name": "Bob Smith",     "email": "bob@example.com" },
      { "name": "   ",          "email": "empty_name@example.com" },
      { "name": "Charlie Davis", "email": "invalid-email-syntax" },
      { "name": "Alice Dupe",    "email": "ALICE@EXAMPLE.COM" }
    ]
  }'
```

#### PowerShell
```powershell
$body = @{
    event_name = "Cloud Native Masterclass"
    issuer     = "Engineering Academy"
    issue_date = "2026-10-07"
    recipients = @(
        @{ name = "Alice Johnson"; email = "alice@example.com" },
        @{ name = "Bob Smith";     email = "bob@example.com" },
        @{ name = "   ";          email = "empty_name@example.com" },
        @{ name = "Charlie Davis"; email = "invalid-email-syntax" },
        @{ name = "Alice Dupe";    email = "ALICE@EXAMPLE.COM" }
    )
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs" -Method Post -ContentType "application/json" -Body $body
$response | Format-List
```

#### Example Response (HTTP 202 Accepted)
```json
{
  "id": "3eec9a25-87f6-49a8-a291-100990334d93",
  "status": "pending",
  "event_name": "Cloud Native Masterclass",
  "issuer": "Engineering Academy",
  "issue_date": "2026-10-07",
  "total": 5,
  "succeeded": 0,
  "failed": 3,
  "created_at": "2026-10-07T16:45:10.123456Z",
  "completed_at": null,
  "progress_percent": 60.0
}
```

---

### Step 2: Poll Job Status & Progress

#### cURL
```bash
curl -X GET http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93
```

#### PowerShell
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93" | ConvertTo-Json -Depth 4
```

#### Example Response (HTTP 200 OK after completion)
```json
{
  "id": "3eec9a25-87f6-49a8-a291-100990334d93",
  "status": "completed_with_errors",
  "event_name": "Cloud Native Masterclass",
  "issuer": "Engineering Academy",
  "issue_date": "2026-10-07",
  "total": 5,
  "succeeded": 2,
  "failed": 3,
  "created_at": "2026-10-07T16:45:10.123456Z",
  "completed_at": "2026-10-07T16:45:10.890123Z",
  "progress_percent": 100.0,
  "certificates": [
    {
      "id": "60fd4ef2-526c-4384-8d9d-7ee962f41a75",
      "job_id": "3eec9a25-87f6-49a8-a291-100990334d93",
      "recipient_name": "Alice Johnson",
      "recipient_email": "alice@example.com",
      "status": "success",
      "error_message": null,
      "file_path": "output/3eec9a25-87f6-49a8-a291-100990334d93/60fd4ef2-526c-4384-8d9d-7ee962f41a75.pdf",
      "created_at": "2026-10-07T16:45:10.123456Z",
      "download_url": "/certificates/60fd4ef2-526c-4384-8d9d-7ee962f41a75/download"
    },
    {
      "id": "71ac8df1-419b-4682-9efa-8aa39b23f819",
      "job_id": "3eec9a25-87f6-49a8-a291-100990334d93",
      "recipient_name": "",
      "recipient_email": "empty_name@example.com",
      "status": "failed",
      "error_message": "Name is empty",
      "file_path": null,
      "created_at": "2026-10-07T16:45:10.123456Z",
      "download_url": null
    }
  ]
}
```

---

### Step 3: List Failed Certificates Only

#### cURL
```bash
curl -X GET "http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93/certificates?status=failed"
```

#### PowerShell
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93/certificates?status=failed" | Format-Table id, recipient_name, error_message
```

---

### Step 4: Download a Single Certificate PDF

#### cURL
```bash
curl -X GET http://127.0.0.1:8000/certificates/60fd4ef2-526c-4384-8d9d-7ee962f41a75/download \
  --output certificate_alice.pdf
```

#### PowerShell
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/certificates/60fd4ef2-526c-4384-8d9d-7ee962f41a75/download" -OutFile "certificate_alice.pdf"
```

---

### Step 5: Download the Whole Job as a ZIP

#### cURL
```bash
curl -X GET http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93/download \
  --output certificates_job.zip
```

#### PowerShell
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/jobs/3eec9a25-87f6-49a8-a291-100990334d93/download" -OutFile "certificates_job.zip"
```

---

## 9. Design Decisions

### Background Processing: FastAPI BackgroundTasks vs Synchronous vs Celery/Redis
FastAPI's built-in `BackgroundTasks` was selected because it is lightweight, zero-dependency, and requires no external message brokers or worker processes to run. A synchronous approach would cause client HTTP connections to hang or timeout while generating hundreds of PDFs. The trade-off with `BackgroundTasks` is that tasks execute within the web server process memory: if the server reboots or crashes, in-progress background jobs are interrupted and lost. In a high-volume, distributed production environment, a persistent task queue such as Celery or RQ backed by Redis would be used for job persistence, retry scheduling, and worker scaling.

### Lenient Recipient Validation vs Strict Schema Rejection
Structural validation errors (empty event title, missing issuer, invalid date, or missing recipient list) are rejected upfront with HTTP 422 Unprocessable Entity. However, individual recipient entries use plain strings in Pydantic schemas. If a batch of 500 recipients contains one malformed email address, failing the entire request at the HTTP boundary would create a poor user experience. Instead, the service layer validates each recipient individually, recording invalid entries directly as `failed` with descriptive error messages, allowing the remaining valid certificates to be generated successfully.

### Failure Isolation and Live Progress Tracking
Each certificate generation is wrapped in an individual `try/except` block and committed to the database immediately upon completion (`db.commit()` inside the processing loop). This ensures that a single rendering exception (e.g. malformed graphics or unexpected character crash) never halts the remainder of the batch. Furthermore, committing per certificate allows clients polling `GET /jobs/{id}` to observe live progress counters incrementing in real time rather than experiencing a static zero count followed by a sudden jump at the end.

### Job Status Lifecycle and Progress Computation
Jobs transition through an explicit state lifecycle: `pending` -> `processing` -> `completed`, `completed_with_errors`, or `failed`. If no recipients pass initial validation, the job immediately marks itself as `failed`. Progress percentage is computed as `((succeeded + failed) / total) * 100.0`. Because `failed` includes both recipients rejected upfront during validation and runtime PDF rendering errors, the sum of `succeeded + failed` represents the total volume of recipients resolved, reaching `100.0%` when every item has been handled.

### Independent Database Session for Background Workers
FastAPI's `Depends(get_db)` session dependency is strictly bound to the HTTP request lifecycle; once the HTTP 202 response is sent, the request session is closed. If a background worker attempted to reuse that session, it would crash with closed connection or detached instance errors. Therefore, `process_job` instantiates its own isolated session using `SessionLocal()` and guarantees session disposal inside a `finally` block.

### UUID File Naming and Stored-Path Serving
Generated files are named on disk using their certificate UUID (`<job_id>/<certificate_id>.pdf`) rather than the recipient's name. This eliminates filename collisions (e.g. two recipients sharing the same name in an event) and prevents illegal filesystem characters across operating systems. When serving files via download endpoints, the API strictly reads the `file_path` recorded in the database by our trusted worker and never accepts arbitrary file paths from user parameters, preventing Directory Traversal (LFI) attacks.

### Atomic PDF Generation with Temporary Files
PDF creation requires sequential disk writes. If the server loses power or the process crashes mid-generation, writing directly to the final file path would leave a corrupted, truncated PDF. The service generates each certificate to a temporary file (`*.tmp_<uuid>.pdf`) and renames it to the destination using `os.replace`. Unlike `os.rename` on Windows (which raises `FileExistsError` if a file exists), `os.replace` provides atomic, cross-platform replacement semantics.

### In-Batch Duplicate Email Handling
Emails are evaluated case-insensitively against a set of previously seen emails within the same submission. The first occurrence is valid; subsequent occurrences are marked failed with `"Duplicate email in request"`. This is an intentional business logic rule designed to prevent sending accidental duplicate certificates for the same event. Because it is implemented as an explicit check in `app/services/validation.py`, it can be toggled or altered without modifying schema or database contracts.

### HTTP 409 Conflict vs HTTP 404 Not Found
When a client requests a certificate that exists in the database but is still in `pending` processing or failed generation, the API returns HTTP 409 Conflict rather than 404 Not Found. HTTP 404 signifies that the resource identifier is unknown. Returning HTTP 409 accurately communicates that the resource exists, but its current lifecycle state conflicts with the download operation.

### On-Demand Disk-Based ZIP Archive Creation
The `GET /jobs/{job_id}/download` endpoint packages all successful certificates into a single ZIP archive. The archive is created on disk in a temporary file and streamed via FastAPI's `FileResponse` with a background cleanup callback (`starlette.background.BackgroundTask`). Constructing the ZIP in memory (`io.BytesIO`) would cause severe RAM spikes when compressing hundreds of certificates, risking Out-Of-Memory (OOM) crashes. Streaming from disk keeps Python memory consumption minimal and predictable.

---

## 10. Known Limitations and Future Improvements
- **Latin-1 Font Limitation**: The default ReportLab Helvetica font only supports Latin-1 character encodings. Non-Latin scripts (Cyrillic, Arabic, Chinese, Devanagari) require registering custom TrueType (TTF) fonts like Google Noto Sans.
- **In-Flight Jobs Lost on Server Restart**: Jobs being processed when the application process terminates will remain stuck in `processing`. A production deployment should use a durable queue (Celery, RQ, or AWS SQS) with a worker heartbeat and job retry mechanism.
- **No Authentication or Authorization**: All endpoints are currently public. Production deployment requires API keys or OAuth2/JWT tokens to restrict job creation and access to tenant-owned certificates.
- **Local Filesystem Storage**: PDFs are currently saved to the local disk. In a cloud environment with multiple horizontally scaled replicas, files should be stored in an object store (e.g., AWS S3 or Google Cloud Storage) with pre-signed download URLs.
- **SQLite Concurrency Limits**: SQLite restricts write operations to a single writer process. While adequate for moderate bulk operations and testing, swapping to PostgreSQL (via `DATABASE_URL`) is recommended for high concurrent write throughput.
- **No Individual Retry Endpoint**: If an individual certificate fails, there is currently no endpoint to retry just that certificate without resubmitting a new job.
- **No Automated Storage Retention/Cleanup**: Generated PDF files remain on disk indefinitely unless manually removed. An asynchronous cleanup cron job or retention policy should be implemented for production storage management.

---

## 11. Project Structure
```text
├── .env.example              # Sample environment variable template
├── .gitignore                # Git exclusions (venv, sqlite databases, output folder)
├── README.md                 # Complete system documentation and usage guide
├── requirements.txt          # Python dependency manifest
├── app/
│   ├── __init__.py           # Application package initializer
│   ├── config.py             # Application settings, limits, and environment parsing
│   ├── database.py           # SQLAlchemy engine, session maker, DeclarativeBase, and get_db dependency
│   ├── main.py               # FastAPI application factory, lifespan table creation, and router registration
│   ├── models.py             # SQLAlchemy ORM models (Job, Certificate) and lifecycle status enums
│   ├── schemas.py            # Pydantic v2 schemas, computed properties (progress_percent, download_url)
│   ├── routers/
│   │   ├── __init__.py       # Routers package initializer
│   │   ├── certificates.py   # Router for single certificate PDF download endpoint
│   │   └── jobs.py           # Router for job creation, progress tracking, and ZIP export endpoints
│   └── services/
│       ├── __init__.py       # Services package initializer
│       ├── jobs.py           # Atomic job creation and initial batch persistence service
│       ├── pdf.py            # ReportLab certificate rendering service with font scaling
│       ├── processing.py     # Background worker executing per-certificate generation and commits
│       └── retrieval.py      # Database query functions, filename sanitization, and disk-based ZIP creation
├── scripts/
│   └── smoke_test.py         # End-to-end smoke test script executed against a live running server
└── tests/
    ├── __init__.py           # Test package initializer
    ├── conftest.py           # Pytest fixtures (in-memory SQLite, session factory, TestClient overrides)
    ├── test_health.py        # Health check endpoint unit test
    ├── test_job_creation.py  # Validation rules and POST /jobs creation unit/integration tests
    ├── test_models_schemas.py# Database schema and model relationship persistence tests
    ├── test_pdf.py           # ReportLab PDF generation, header validation, and font-scaling tests
    ├── test_processing.py    # Background worker execution, crash resilience, and idempotency tests
    └── test_retrieval.py     # Progress tracking, status filtering, download conflict, and ZIP export tests
```
