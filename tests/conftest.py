import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Never touch the user's application database or contact Gemini during tests.
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['DEMO_DATA'] = 'false'
os.environ['GEMINI_API_KEY'] = ''

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.migrations import initialize_database


@pytest.fixture
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    initialize_database(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
