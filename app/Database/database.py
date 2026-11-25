from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config.Config import settings


def get_db_url(raw_url: str) -> str:
    """Normaliza la URL de base de datos para compatibilidad con SQLAlchemy 2.0 y Supabase."""
    url = raw_url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def create_db_engine(db_url: str):
    normalized_url = get_db_url(db_url)
    if normalized_url.startswith("sqlite"):
        return create_engine(
            normalized_url,
            connect_args={"check_same_thread": False}
        )
    # Configuración optimizada de Connection Pooling para PostgreSQL / Supabase
    return create_engine(
        normalized_url,
        pool_pre_ping=True,      # Comprueba que la conexión siga viva antes de usarla
        pool_recycle=300,        # Recicla conexiones cada 5 min para prevenir cortes por cortafuegos cloud
        pool_size=10,            # Conexiones base en pool
        max_overflow=20          # Conexiones temporales adicionales bajo alta concurrencia
    )


engine = create_db_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()