from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

# SQLite requires 'check_same_thread: False' to allow multi-threaded access
# (common in web servers like FastAPI handling concurrent requests).
# Non-SQLite databases (such as PostgreSQL) do not need this argument.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Create the SQLAlchemy engine that manages database connection pools
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Session factory for creating individual database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    SQLAlchemy 2.x Declarative Base class.
    All database models inherit from this class to register their table schemas.
    """
    pass


def get_db():
    """
    FastAPI dependency yielding a database session per HTTP request.
    Guarantees that the session is properly closed once the request finishes,
    preventing connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
