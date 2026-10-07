import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# StaticPool ensures that all connections use the exact same in-memory SQLite database,
# even when accessed across different threads or sessions during a test.
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """
    Creates fresh database tables for each test and drops them on teardown,
    providing complete test isolation without touching disk.
    """
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def session_factory():
    """
    Provides the test sessionmaker bound to the in-memory SQLite database,
    allowing tests and background workers to open isolated test sessions.
    """
    return TestingSessionLocal


@pytest.fixture(scope="function")
def client(db_session, monkeypatch, tmp_path):
    """
    FastAPI TestClient fixture that overrides the app's get_db dependency
    and ensures background tasks use the isolated test database and temporary output directory.
    """
    from app.services import processing

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(processing, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(processing, "OUTPUT_DIR", tmp_path)

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
