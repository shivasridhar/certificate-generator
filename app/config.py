import os
from pathlib import Path

# Base directory of the project root
BASE_DIR = Path(__file__).resolve().parent.parent

# Database connection URL
# Defaults to a local SQLite database file in the project root.
# In production, this can be swapped to PostgreSQL without code changes
# by setting the DATABASE_URL environment variable:
# e.g., postgresql+psycopg2://user:password@localhost:5432/certificates_db
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'certificates.db'}")

# Directory where generated PDF certificates will be saved
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))

# Maximum number of recipients allowed per bulk job submission
# Protects against server memory spikes and excessively large payload processing
MAX_RECIPIENTS_PER_JOB = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "1000"))
