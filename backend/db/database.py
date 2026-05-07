from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL Connection URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docchat_db")

# Force asyncpg driver (Supabase gives postgresql:// by default, which causes the psycopg2 error)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def run_lightweight_migrations():
    """Idempotently add columns introduced after the original schema."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE document_chunks "
            "ADD COLUMN IF NOT EXISTS user_id VARCHAR "
            "REFERENCES users(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_user_id "
            "ON document_chunks (user_id)"
        ))
