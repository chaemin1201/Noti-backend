from sqlalchemy import Integer, String, DateTime, Boolean, ARRAY, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from ..models.problem import Problem

class MultipleChoiceProblem(Problem):
    __tablename__ = "multiple_choice_problem"

    problem_id: Mapped[int] = mapped_column(Integer, ForeignKey("problem.problem_id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True)
    options: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: [], nullable=False)  # 선택지들
    correct_answers: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [], nullable=False)  # 정답 인덱스들

    rating_mode: Mapped[str | None] = mapped_column(String, default=None, nullable=True)  # 채점 모드 (예: "exact", "partial", "soft", "none")
    __mapper_args__ = {
        "polymorphic_identity": "multiple_choice"
    }