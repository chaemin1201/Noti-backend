from sqlalchemy import Integer, String, DateTime, Boolean, ARRAY, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from ..models.problem import Problem
from sqlalchemy.types import Enum as SQLEnum
from enum import Enum as PyEnum

class ShortAnswerRatingMode(str, PyEnum):
    exact = "exact"  # 정확한 답변을 요구
    partial = "partial"  # 부분 점수를 허용
    soft = "soft"  # 유연한 채점 기준
    none = "none"  # 채점하지 않음

class ShortAnswerProblem(Problem):
    __tablename__ = "short_answer_problem"

    problem_id: Mapped[int] = mapped_column(Integer, ForeignKey("problem.problem_id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True)
    
    answer_text: Mapped[list[str] | dict[str, list[str]]] = mapped_column(
        JSONB, 
        nullable=False  # 하나는 항상 존재
    )
    
    # 채점 모드 (예: "exact", "partial", "soft", "none")
    rating_mode: Mapped[ShortAnswerRatingMode] = mapped_column(
        SQLEnum(ShortAnswerRatingMode, name="short_answer_rating_mode_enum", 
                create_constraint=True),
            default=ShortAnswerRatingMode.exact,
            nullable=False
        )  
    
    # 채점 기준
    grading_criteria: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None, nullable=True)  # 채점 기준 설명

    __mapper_args__ = {
        "polymorphic_identity": "short_answer"
    }