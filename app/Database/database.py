import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config.Config import settings


class Base(DeclarativeBase):
    pass


def get_db_url(raw_url: str) -> str:
    """Normaliza y limpia la URL de base de datos para compatibilidad con SQLAlchemy 2.0 y Supabase."""
    url = raw_url.strip()
    # Corregir si accidentalmente se coló un caracter antes de postgres (ej: 'ypostgresql://')
    if "postgres" in url and not (url.startswith("postgres://") or url.startswith("postgresql://")):
        idx = url.find("postgres")
        if idx > 0 and url[idx-1] not in "+:":
            url = url[idx:]
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def auto_sync_sqlite_to_target(target_engine):

    sqlite_path = Path("p2p_monitor.db")
    if not sqlite_path.exists():
        return

    try:
        from app.Models.models import AlertLog, MarketSnapshot
        Base.metadata.create_all(bind=target_engine)

        TargetSession = sessionmaker(bind=target_engine)
        target_session = TargetSession()

   
        count_target = target_session.query(MarketSnapshot).count()
        if count_target == 0:
            print(" [MIGRACIÓN AUTOMÁTICA] Detectada base de Supabase sin datos. Iniciando copia desde SQLite...")
            sqlite_engine = create_engine(
                "sqlite:///./p2p_monitor.db",
                connect_args={"check_same_thread": False}
            )
            SourceSession = sessionmaker(bind=sqlite_engine)
            source_session = SourceSession()

            # Migrar MarketSnapshot
            snapshots = source_session.query(MarketSnapshot).order_by(MarketSnapshot.id.asc()).all()
            if snapshots:
                new_snapshots = [
                    MarketSnapshot(**{col.name: getattr(s, col.name) for col in s.__table__.columns})
                    for s in snapshots
                ]
                target_session.add_all(new_snapshots)
                target_session.commit()
                print(f"   ✅ [MIGRACIÓN AUTOMÁTICA] {len(new_snapshots)} registros de mercado copiados a Supabase.")

            # Migrar AlertLog
            alerts = source_session.query(AlertLog).order_by(AlertLog.id.asc()).all()
            if alerts:
                new_alerts = [
                    AlertLog(**{col.name: getattr(a, col.name) for col in a.__table__.columns})
                    for a in alerts
                ]
                target_session.add_all(new_alerts)
                target_session.commit()
                print(f"   [MIGRACIÓN AUTOMÁTICA] {len(new_alerts)} registros de alertas copiados a Supabase.")

            # Sincronizar secuencias de IDs en PostgreSQL
            if target_engine.dialect.name == "postgresql":
                with target_engine.begin() as conn:
                    for table in ["market_snapshot", "alert_logs"]:
                        try:
                            conn.execute(text(
                                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) FROM {table};"
                            ))
                        except Exception:
                            pass

            source_session.close()
            print("🎉 [MIGRACIÓN AUTOMÁTICA] ¡Todos tus datos históricos ya están en Supabase!")
        target_session.close()
    except Exception as e:
        print(f"⚠️ [MIGRACIÓN AUTOMÁTICA] Aviso al verificar sincronización: {e}")


def initialize_engine():
    """
    Detecta si existe una conexión configurada con Supabase / PostgreSQL.
    Si la conexión es exitosa:
        - Activa Supabase (PostgreSQL)
        - DESACTIVA COMPLETAMENTE SQLite
        - Migra los datos históricos automáticamente si es necesario
    Si falla o no está configurado:
        - Utiliza SQLite como respaldo local
    """
    target_url = settings.SUPABASE_DATABASE_URL or settings.DATABASE_URL
    if target_url and ("postgres" in target_url):
        normalized_url = get_db_url(target_url)
        try:
            pg_engine = create_engine(
                normalized_url,
                pool_pre_ping=True,      # Comprueba que la conexión siga viva antes de usarla
                pool_recycle=300,        # Recicla conexiones cada 5 min para prevenir cortes por cortafuegos cloud
                pool_size=10,            # Conexiones base en pool
                max_overflow=20          # Conexiones temporales adicionales bajo alta concurrencia
            )
            # Probar conexión real
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            print("\n" + "=" * 70)
            print("🚀 [DATABASE] ¡Conexión con Supabase (PostgreSQL) EXITOSA!")
            print("🛑 [DATABASE] SQLite ha sido COMPLETAMENTE DESACTIVADO.")
            print("☁️ [DATABASE] Todas las lecturas y escrituras se realizan en Supabase.")
            print("=" * 70 + "\n")

            return pg_engine, "POSTGRESQL"
        except Exception as e:
            print("\n" + "=" * 70)
            print(f"⚠️ [DATABASE] Error al conectar con Supabase (PostgreSQL): {e}")
            print("🔄 [DATABASE] Continuando con SQLite local como respaldo temporal.")
            print("=" * 70 + "\n")

  
    sqlite_url = settings.DATABASE_URL if settings.DATABASE_URL.startswith("sqlite") else "sqlite:///./p2p_monitor.db"
    sqlite_engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False}
    )
    print("📁 [DATABASE] Usando base de datos SQLite local.")
    return sqlite_engine, "SQLITE"


engine, ACTIVE_DB_TYPE = initialize_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
