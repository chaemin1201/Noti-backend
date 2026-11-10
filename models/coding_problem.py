from sqlalchemy import Integer, String, DateTime, Boolean, ARRAY, ForeignKey
from enum import Enum as PyEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from ..models.problem import Problem
from sqlalchemy.types import Enum as SQLEnum


class CodingRatingMode(str, PyEnum):
    space = "space"
    regex = "regex"
    hard = "hard"
    none = "none"

class CodingProblem(Problem):
    __tablename__ = "coding_problem"

    problem_id: Mapped[int] = mapped_column(Integer, ForeignKey("problem.problem_id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True)
    
    
    # 상세 채점 모드 (예: "space", "regex", "hard", "none")
    # 이 모드는 문제의 채점 방식을 정의합니다.
    rating_mode: Mapped[CodingRatingMode] = mapped_column(
        SQLEnum(CodingRatingMode, name="coding_rating_mode_enum", create_constraint=True),
        default=CodingRatingMode.none,
        nullable=False
    )

    # {input: str, output: str, is_hidden): bool} 형태의 테스트 케이스들
    test_cases: Mapped[list[dict[str, str | bool]] | None] = mapped_column(JSONB, default=None, nullable=True)  
    
    # {language: str, code: str, is_main: bool} 형태의 참고 코드들    
    reference_codes: Mapped[list[dict[str, str | bool]]| None] = mapped_column(JSONB, default=None, nullable=False)  
    
    # AI 채점용 조건들 (예: ["for문을 사용해야합니다", "입력은 1부터 100까지의 정수여야 합니다"])
    # 이 조건들은 AI 채점 시에 사용됩니다. 
    # 예를 들어, "for문을 사용해야 합니다"라는 조건이 있다면, AI는 제출된 코드가 for문을 사용하는지 확인할 수 있습니다.
    problem_condition: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: [], nullable=True)  
    
    #  처음 제공될 코드폼 지정:
    base_code: Mapped[list[dict[str,str]]] = mapped_column(JSONB, default=lambda: [], nullable=False)  # 기본 코드 (예: 문제 설명에 포함된 코드 스니펫)
    
    __mapper_args__ = {
        "polymorphic_identity": "coding",
        "with_polymorphic": "*"
    }
class DebuggingProblem(CodingProblem):
    __mapper_args__ = {
        "polymorphic_identity": "debugging"
    }