from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config.Config import settings

connect_args = {"check_same_thread":False} if settings.Database_Url.startswith("sqlite") else {}
engine =  create_engine(settings.Database_Url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db

    finally:
        db.close()