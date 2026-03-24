from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError
from datetime import datetime, timezone

Base = declarative_base()

class ChatHistory(Base):
    __tablename__ = 'chat_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(50), nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class MemoryTraits(Base):
    __tablename__ = 'memory_traits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False) # 'user' or 'pet'
    trait_description = Column(Text, nullable=False)

def init_db(db_url: str = 'postgresql://user:pass@localhost:5432/pet_db'):
    """Initialize the database engine and create tables if they don't exist."""
    engine = create_engine(db_url)
    try:
        # Check connection
        with engine.connect() as conn:
            pass
        Base.metadata.create_all(engine)
        print("Database connected and initialized.")
        return sessionmaker(bind=engine)
    except OperationalError as e:
        print(f"Warning: Could not connect to PostgreSQL database. Make sure it is running.\nError: {e}")
        return None
