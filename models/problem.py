from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Boolean, ARRAY, ForeignKey, Text, Float
from enum import Enum as PyEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from typing import Dict, List
from sqlalchemy import Enum as SQLEnum, Index, text

from app.database import Base

class ProblemTypeEnum(str, PyEnum):
    coding = "coding"
    multiple_choice = "multiple_choice"
    short_answer = "short_answer"
    subjective = "subjective"
    debugging = "debugging"
    코딩 = "코딩"
    디버깅 = "디버깅"
    객관식 = "객관식"
    단답형 = "단답형"
    주관식 = "주관식"
    
class sync_policy_enum(str, PyEnum):
    mine = "mine"
    follow = "follow"
    fork = "fork"

class Problem(Base):
    __tablename__ = "problem"
    __table_args__ = (
        # 같은 사용자가 같은 내용(content_hash)의 문제를 둘 이상 갖지 못하게 DB 가 막는다 (삭제된 문제는 제외).
        # 앱의 중복 검사(select 후 insert)가 동시 요청에서 뚫려도 마지막 방어선이 된다.
        Index("uq_problem_maker_content_hash", "maker_id", "temporary_field_str_2", unique=True,
              postgresql_where=text("is_deleted = false AND temporary_field_str_2 IS NOT NULL"),
              sqlite_where=text("is_deleted = 0 AND temporary_field_str_2 IS NOT NULL")),   # 로컬 SQLite 테스트용
        # 등록 제목 코드(PY41_0007)는 서로 겹치지 않는다. 삭제된 문제의 번호도 다시 쓰지 않는다. 옛 한글 제목은 대상이 아니다.
        Index("uq_problem_title_code", "title", unique=True,
              postgresql_where=text("title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$'"),
              sqlite_where=text("title GLOB '[A-Z]*_[0-9][0-9][0-9][0-9]*'")),
    )

    problem_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    maker_id: Mapped[str] = mapped_column(String, ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    description_style: Mapped[str | None] = mapped_column(Text, nullable=True)  # CSS 포함 스타일 포함한 데이터
    difficulty: Mapped[str] = mapped_column(String, nullable=False)
    problem_type: Mapped[ProblemTypeEnum] = mapped_column(
        SQLEnum(ProblemTypeEnum, name="problem_type_enum", native_enum=False), nullable=False)  # coding, multiple_choice, short_answer, subjective

    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: [], nullable=False)
    
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    
    attached_files: Mapped[List | None] = mapped_column(JSONB, nullable=True, default=None)
    
    prev_problem_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("problem.problem_id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, nullable=True)
    
    
    total_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    
    # 임시 필드들 사용시 주석으로 사용 용도 표시
    temporary_field_int_1: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 임시 필드 1 (정수)
    temporary_field_int_2: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 임시 필드 2 (정수)
    temporary_field_int_3: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 임시 필드 3 (정수)
    temporary_field_int_4: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 임시 필드 4 (정수)
    temporary_field_int_5: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 임시 필드 5 (정수)
    
    temporary_field_str_1: Mapped[str | None] = mapped_column(String(100), nullable=False, default="mine")  # 문제 저장 상태 sync_policy
    temporary_field_str_2: Mapped[str | None] = mapped_column(String(100), nullable=True)  # content_hash 문제 중복 체크용
    temporary_field_str_3: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 원본 문제 ID (follow 정책용)
    temporary_field_str_4: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 임시 필드 4 (문자열)
    temporary_field_str_5: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 임시 필드 5 (문자열)

    temporary_field_datetime_1: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 임시 필드 1 (날짜/시간)
    temporary_field_datetime_2: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 임시 필드 2 (날짜/시간)

    temporary_field_json: Mapped[Dict | None] = mapped_column(JSONB, nullable=True)  # 임시 JSON 필드 (구조화 데이터 저장용)

    # 추가 필드 필요 시 연결되는 테이블 링크
    temporary_table_link: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    __mapper_args__ = {
    "polymorphic_on": problem_type,
    "with_polymorphic": "*"
    }