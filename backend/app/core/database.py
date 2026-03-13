from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# Normalise the driver — support asyncpg, psycopg (v3) and psycopg2 URLs.
# On Windows, asyncpg has known compatibility issues with Docker Desktop
# (WinError 64). psycopg3 (postgresql+psycopg) is the recommended alternative.
_db_url = settings.database_url
if _db_url.startswith("postgresql+psycopg2://"):
    # psycopg2 is sync-only; upgrade to psycopg3 async driver automatically
    _db_url = _db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
elif _db_url.startswith("postgresql://") or _db_url.startswith("postgresql+asyncpg://"):
    # Fallback: try replacing asyncpg with psycopg for Windows compatibility
    _db_url = _db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(
    _db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.app_env == "development",
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()