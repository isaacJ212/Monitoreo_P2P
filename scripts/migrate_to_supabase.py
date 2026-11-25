#!/usr/bin/env python3
"""
Script de Migración de Datos Históricos: SQLite -> Supabase (PostgreSQL)
========================================================================
Este script migra de forma segura todos los registros históricos de:
1. `market_snapshot` (Precios, spreads, comerciantes, límites y métodos de pago)
2. `alert_logs` (Historial de alertas y notificaciones enviadas)

Uso:
    python scripts/migrate_to_supabase.py --target-url="postgresql://postgres.[ref]:[pass]@aws-0-[region].pooler.supabase.com:6543/postgres"

O configurando la variable de entorno:
    export TARGET_DATABASE_URL="postgresql://postgres.[ref]:[pass]@aws-0-[region].pooler.supabase.com:6543/postgres"
    python scripts/migrate_to_supabase.py
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Añadir el directorio raíz al path para importar módulos de la app
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config.Config import settings
from app.Database.database import Base, create_db_engine, get_db_url
from app.Models.models import AlertLog, MarketSnapshot


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Migrar datos históricos de P2P Monitor desde SQLite a Supabase PostgreSQL."
    )
    parser.add_argument(
        "--source-url",
        type=str,
        default=os.getenv("SOURCE_DATABASE_URL", settings.DATABASE_URL),
        help="URL de la base de datos origen (por defecto SQLite local).",
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default=os.getenv("TARGET_DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL"),
        help="URL de conexión de Supabase PostgreSQL (ej: postgresql://postgres.ref:pass@host:6543/postgres).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Si se activa, vacía las tablas en el destino antes de migrar.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Tamaño del lote de inserción (por defecto 100).",
    )
    return parser.parse_args()


def test_connection(engine, label: str):
    """Verifica que la conexión a la base de datos sea válida."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"✅ Conexión exitosa a {label}")
        return True
    except Exception as e:
        print(f"❌ Error al conectar con {label}: {e}")
        return False


def migrate_table(model, source_session: Session, target_session: Session, batch_size: int, clean: bool):
    """Migra los registros de un modelo de la base origen a la base destino."""
    table_name = model.__tablename__
    print(f"\n📦 Iniciando migración de la tabla: '{table_name}'...")

    if clean:
        print(f"   🧹 Limpiando registros existentes en destino para '{table_name}'...")
        target_session.query(model).delete()
        target_session.commit()

    # Obtener IDs existentes en destino para evitar duplicados si no se usó --clean
    existing_ids = set()
    if not clean:
        existing_ids = {row[0] for row in target_session.query(model.id).all()}
        if existing_ids:
            print(f"   ℹ️ Detectados {len(existing_ids)} registros ya existentes en destino. Se omitirán duplicados.")

    # Consultar origen ordenado por ID ascendente
    source_query = source_session.query(model).order_by(model.id.asc())
    total_source = source_query.count()
    print(f"   📊 Registros encontrados en origen: {total_source}")

    if total_source == 0:
        print(f"   ⚠️ No hay datos para migrar en '{table_name}'.")
        return 0, 0

    inserted_count = 0
    skipped_count = 0
    batch = []

    for item in source_query.yield_per(batch_size):
        if item.id in existing_ids:
            skipped_count += 1
            continue

        # Crear nuevo objeto desvinculado con los mismos datos
        item_data = {col.name: getattr(item, col.name) for col in item.__table__.columns}
        new_instance = model(**item_data)
        batch.append(new_instance)

        if len(batch) >= batch_size:
            target_session.add_all(batch)
            target_session.commit()
            inserted_count += len(batch)
            print(f"   ⏳ Progreso '{table_name}': {inserted_count}/{total_source} migrados...", end="\r")
            batch = []

    if batch:
        target_session.add_all(batch)
        target_session.commit()
        inserted_count += len(batch)

    print(f"   ✅ Finalizado '{table_name}': {inserted_count} insertados, {skipped_count} omitidos.")
    return inserted_count, skipped_count


def reset_postgres_sequences(engine):
    """En PostgreSQL, sincroniza los auto-incrementos (sequences) al valor máximo insertado."""
    if engine.dialect.name != "postgresql":
        return

    print("\n🔄 Sincronizando secuencias de auto-incremento en PostgreSQL...")
    tables = [MarketSnapshot.__tablename__, AlertLog.__tablename__]
    with engine.begin() as conn:
        for table in tables:
            try:
                query = text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) FROM {table};"
                )
                conn.execute(query)
                print(f"   ✅ Secuencia de '{table}' sincronizada correctamente.")
            except Exception as e:
                print(f"   ⚠️ No se pudo sincronizar secuencia de '{table}': {e}")


def main():
    args = parse_arguments()

    print("=" * 70)
    print("🚀 MIGRACIÓN DE DATOS P2P MONITOR: SQLite -> Supabase PostgreSQL")
    print("=" * 70)

    target_url = args.target_url
    if not target_url:
        print("\n⚠️ No se especificó la URL de destino de Supabase.")
        print("Ejemplo de formato:")
        print("  postgresql://postgres.[TU_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres\n")
        try:
            target_url = input("Ingresa la URL de conexión a Supabase: ").strip()
        except EOFError:
            target_url = ""

    if not target_url:
        print("❌ Error: Debes proporcionar una URL válida para Supabase. Abortando.")
        sys.exit(1)

    source_url = args.source_url
    print(f"\n📍 Origen:  {source_url}")
    print(f"📍 Destino: {target_url.split('@')[-1] if '@' in target_url else target_url}")

    # Crear engines
    source_engine = create_db_engine(source_url)
    target_engine = create_db_engine(target_url)

    # Probar conexiones
    if not test_connection(source_engine, "Base de Datos Origen"):
        sys.exit(1)
    if not test_connection(target_engine, "Base de Datos Destino (Supabase)"):
        sys.exit(1)

    # Crear tablas en el destino si no existen
    print("\n🛠️ Verificando y creando esquemas de tablas en Supabase...")
    Base.metadata.create_all(bind=target_engine)
    print("✅ Tablas listas en Supabase ('market_snapshot', 'alert_logs').")

    # Sesiones
    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)

    source_session = SourceSession()
    target_session = TargetSession()

    start_time = datetime.now()

    try:
        # Migrar MarketSnapshot
        snapshots_inserted, snapshots_skipped = migrate_table(
            MarketSnapshot, source_session, target_session, args.batch_size, args.clean
        )

        # Migrar AlertLog
        alerts_inserted, alerts_skipped = migrate_table(
            AlertLog, source_session, target_session, args.batch_size, args.clean
        )

        # Sincronizar secuencias en PostgreSQL
        reset_postgres_sequences(target_engine)

        # Verificación final de conteos
        target_snapshots = target_session.query(MarketSnapshot).count()
        target_alerts = target_session.query(AlertLog).count()
        source_snapshots = source_session.query(MarketSnapshot).count()
        source_alerts = source_session.query(AlertLog).count()

        duration = (datetime.now() - start_time).total_seconds()

        print("\n" + "=" * 70)
        print("🎉 REPORTE FINAL DE MIGRACIÓN")
        print("=" * 70)
        print(f"⏱️ Tiempo total: {duration:.2f} segundos")
        print(f"📊 Tabla 'market_snapshot': Origen = {source_snapshots} | Destino = {target_snapshots}")
        print(f"📊 Tabla 'alert_logs':      Origen = {source_alerts} | Destino = {target_alerts}")
        print("=" * 70)
        print("✨ ¡Migración completada exitosamente! Ya puedes actualizar tu .env con la URL de Supabase.")

    except Exception as e:
        print(f"\n❌ Ocurrió un error inesperado durante la migración: {e}")
        target_session.rollback()
        raise e
    finally:
        source_session.close()
        target_session.close()


if __name__ == "__main__":
    main()
