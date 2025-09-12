from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# Create schema if not exists
with engine.connect() as conn:
    conn.execute(CreateSchema('delivery_route_optimizer', if_not_exists=True))
    conn.commit()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
Base.metadata.schema = 'delivery_ route_optimizer'

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
