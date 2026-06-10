from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(100), nullable=False, unique=True, index=True)  # 로그인 아이디
    password_hash = Column(String(255), nullable=False)
    name          = Column(String(100), nullable=False)
    email         = Column(String(255), nullable=False, unique=True, index=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    documents = relationship("Document", back_populates="user")
