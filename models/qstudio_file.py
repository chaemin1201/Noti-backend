from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from enum import Enum as PyEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class QstudioActionEnum(str, PyEnum):
    EXPORT = "export"
    IMPORT = "import"


class QstudioFile(Base):
    __tablename__ = "qstudio_file"

    qstudio_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)
    action: Mapped[QstudioActionEnum] = mapped_column(
        SQLEnum(QstudioActionEnum, name="qstudio_action_enum", native_enum=False),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)