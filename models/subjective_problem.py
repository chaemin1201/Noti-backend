from sqlalchemy import Integer, String, DateTime, Boolean, ARRAY, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from ..models.problem import Problem
from sqlalchemy.types import Enum as SQLEnum
from enum import Enum as PyEnum

class AutoRatingMode(str, PyEnum):
    active = "active"  # AI 채점 활성화
    deactive = "deactive"  # AI 채점 비활성화

class SubjectiveProblem(Problem):
    __tablename__ = "subjective_problem"
    
    problem_id: Mapped[int] = mapped_column(Integer, ForeignKey("problem.problem_id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True)
    
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)  # 주관식 문제의 정답들
    
    # AI 채점 모드 (예: "activate", "deactivate")
    rating_mode: Mapped[AutoRatingMode] = mapped_column(
        SQLEnum(AutoRatingMode, name="auto_rating_mode_enum", create_constraint=True),
        default=AutoRatingMode.deactive,
        nullable=False
    )  
    
    # 채점 기준
    grading_criteria: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None, nullable=True)  # 채점 기준 설명

    __mapper_args__ = {
        "polymorphic_identity": "subjective",
    }