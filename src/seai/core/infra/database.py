"""
SQLAlchemy ORM 数据库模块
提供关系型数据库支持：会话、记忆、技能、用户、进化日志等模型
支持 SQLite（默认）和 PostgreSQL
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, JSON, Index, event
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from loguru import logger


DATABASE_URL = os.environ.get(
    "SEAI_DATABASE_URL",
    f"sqlite:///{Path(os.environ.get('SEAI_DATA', str(Path.cwd().parent / 'data'))) / 'seai.db'}"
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)
    title = Column(String(256), default="新会话")
    username = Column(String(64), default="anonymous", index=True)
    model = Column(String(64), default="")
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_archived = Column(Boolean, default=False)

    messages = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan", order_by="MessageModel.created_at")


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, default="")
    tool_calls = Column(JSON, nullable=True)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("SessionModel", back_populates="messages")


class MemoryModel(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    mem_type = Column(String(32), default="text")
    username = Column(String(64), default="anonymous", index=True)
    importance = Column(Float, default=0.5)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_accessed = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    access_count = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_memories_username_type", "username", "mem_type"),
    )


class SkillModel(Base):
    __tablename__ = "skills"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    version = Column(String(32), default="1.0.0")
    author = Column(String(64), default="")
    category = Column(String(64), default="general")
    is_enabled = Column(Boolean, default=True)
    config = Column(JSON, nullable=True)
    install_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class EvolutionLogModel(Base):
    __tablename__ = "evolution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), default="anonymous", index=True)
    action = Column(String(64), nullable=False)
    description = Column(Text, default="")
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    success = Column(Boolean, default=True)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), default="anonymous", index=True)
    action = Column(String(64), nullable=False)
    resource = Column(String(128), default="")
    detail = Column(Text, default="")
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info(f"数据库初始化完成: {DATABASE_URL}")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DatabaseManager:
    """数据库管理器：提供便捷的 CRUD 操作"""

    def __init__(self):
        self._session_factory = SessionLocal

    def _get_db(self) -> Session:
        return self._session_factory()

    def create_session(self, session_id: str, title: str = "新会话", username: str = "anonymous", model: str = "") -> SessionModel:
        with self._get_db() as db:
            s = SessionModel(id=session_id, title=title, username=username, model=model)
            db.add(s)
            db.commit()
            db.refresh(s)
            return s

    def get_session(self, session_id: str) -> Optional[SessionModel]:
        with self._get_db() as db:
            return db.query(SessionModel).filter(SessionModel.id == session_id).first()

    def list_sessions(self, username: str = None, limit: int = 50) -> list:
        with self._get_db() as db:
            q = db.query(SessionModel).filter(SessionModel.is_archived == False)
            if username:
                q = q.filter(SessionModel.username == username)
            return q.order_by(SessionModel.updated_at.desc()).limit(limit).all()

    def delete_session(self, session_id: str):
        with self._get_db() as db:
            db.query(SessionModel).filter(SessionModel.id == session_id).delete()
            db.commit()

    def add_message(self, session_id: str, role: str, content: str, token_count: int = 0) -> MessageModel:
        with self._get_db() as db:
            m = MessageModel(session_id=session_id, role=role, content=content, token_count=token_count)
            db.add(m)
            s = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if s:
                s.message_count = (s.message_count or 0) + 1
                s.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(m)
            return m

    def get_messages(self, session_id: str, limit: int = 100) -> list:
        with self._get_db() as db:
            return db.query(MessageModel).filter(
                MessageModel.session_id == session_id
            ).order_by(MessageModel.created_at.asc()).limit(limit).all()

    def add_memory(self, content: str, mem_type: str = "text", username: str = "anonymous", importance: float = 0.5) -> MemoryModel:
        with self._get_db() as db:
            m = MemoryModel(content=content, mem_type=mem_type, username=username, importance=importance)
            db.add(m)
            db.commit()
            db.refresh(m)
            return m

    def search_memories(self, keyword: str, username: str = None, limit: int = 20) -> list:
        with self._get_db() as db:
            q = db.query(MemoryModel).filter(MemoryModel.content.contains(keyword))
            if username:
                q = q.filter(MemoryModel.username == username)
            results = q.order_by(MemoryModel.created_at.desc()).limit(limit).all()
            for r in results:
                r.access_count = (r.access_count or 0) + 1
                r.last_accessed = datetime.now(timezone.utc)
            db.commit()
            return results

    def log_evolution(self, username: str, action: str, description: str = "", success: bool = True, score: float = None) -> EvolutionLogModel:
        with self._get_db() as db:
            e = EvolutionLogModel(username=username, action=action, description=description, success=success, score=score)
            db.add(e)
            db.commit()
            db.refresh(e)
            return e

    def log_audit(self, username: str, action: str, resource: str = "", detail: str = "", ip_address: str = None) -> AuditLogModel:
        with self._get_db() as db:
            a = AuditLogModel(username=username, action=action, resource=resource, detail=detail, ip_address=ip_address)
            db.add(a)
            db.commit()
            db.refresh(a)
            return a

    def get_stats(self) -> dict:
        with self._get_db() as db:
            return {
                "total_sessions": db.query(SessionModel).count(),
                "total_messages": db.query(MessageModel).count(),
                "total_memories": db.query(MemoryModel).count(),
                "total_skills": db.query(SkillModel).count(),
                "total_evolutions": db.query(EvolutionLogModel).count(),
            }


class AsyncDatabaseManager:
    """异步数据库管理器：将所有同步操作包装到线程池执行"""

    def __init__(self, sync_manager: DatabaseManager = None):
        import asyncio
        self._sync = sync_manager or db_manager
        self._loop = None

    async def _run(self, func, *args, **kwargs):
        import asyncio
        return await asyncio.to_thread(func, *args, **kwargs)

    async def create_session(self, *args, **kwargs):
        return await self._run(self._sync.create_session, *args, **kwargs)

    async def get_session(self, *args, **kwargs):
        return await self._run(self._sync.get_session, *args, **kwargs)

    async def list_sessions(self, *args, **kwargs):
        return await self._run(self._sync.list_sessions, *args, **kwargs)

    async def delete_session(self, *args, **kwargs):
        return await self._run(self._sync.delete_session, *args, **kwargs)

    async def add_message(self, *args, **kwargs):
        return await self._run(self._sync.add_message, *args, **kwargs)

    async def get_messages(self, *args, **kwargs):
        return await self._run(self._sync.get_messages, *args, **kwargs)

    async def add_memory(self, *args, **kwargs):
        return await self._run(self._sync.add_memory, *args, **kwargs)

    async def search_memories(self, *args, **kwargs):
        return await self._run(self._sync.search_memories, *args, **kwargs)

    async def log_evolution(self, *args, **kwargs):
        return await self._run(self._sync.log_evolution, *args, **kwargs)

    async def log_audit(self, *args, **kwargs):
        return await self._run(self._sync.log_audit, *args, **kwargs)

    async def get_stats(self, *args, **kwargs):
        return await self._run(self._sync.get_stats, *args, **kwargs)


db_manager = DatabaseManager()
async_db_manager = AsyncDatabaseManager(db_manager)
