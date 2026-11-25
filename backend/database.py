import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


@event.listens_for(Engine, 'connect')
def enable_sqlite_foreign_keys(connection, _):
    if isinstance(connection, sqlite3.Connection):
        cursor=connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()


DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{(ROOT / "data/smartspend.db").as_posix()}')
(ROOT / 'data').mkdir(exist_ok=True)
engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session
