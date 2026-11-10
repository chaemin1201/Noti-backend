# app/inputdata/intake/models.py
"""업로드 작업(IntakeJob)과 그 결과 항목(IntakeItem). 서버 DB 에 새 테이블 2개가 생긴다."""
import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")

# 항목 상태
PENDING = "pending"                  # AI 처리 대기
PROCESSING = "processing"
AI_FAILED = "ai_failed"              # AI 호출/출력 오류 (resume 으로 다시 시도)
READY = "ready"                      # 검사 통과, 확인할 것 없음 (auto_register 가 꺼진 경우만 남음)
NEEDS_REVIEW = "needs_review"        # 검사 통과, 사람이 확인(승인)해야 등록
BLOCKED = "blocked"                  # 검사 불통과 (수정하면 다시 등록 가능)
NEEDS_INPUT = "needs_input"      # 서술형 모범 답안처럼 사람이 직접 입력해야 하는 값이 비어 있음 (입력하면 승인 대기로 넘어감)
HELD = "held"                        # AI 가 보류 (정보 부족·이름 밀림·이미지뿐 등)
REGISTERED = "registered"
DUPLICATE = "duplicate"              # 이미 등록된 문제라 건너뜀
REGISTER_FAILED = "register_failed"  # 등록 중 오류
SKIPPED = "skipped"                  # 사람이 제외함

APPROVABLE = {READY, NEEDS_REVIEW, REGISTER_FAILED}
EDITABLE = {READY, NEEDS_REVIEW, NEEDS_INPUT, BLOCKED, HELD, REGISTER_FAILED}
ALL_STATUS = [PENDING, PROCESSING, AI_FAILED, READY, NEEDS_REVIEW, NEEDS_INPUT, BLOCKED, HELD, REGISTERED, DUPLICATE, REGISTER_FAILED, SKIPPED]


class ProblemTitleSeq(Base):
    """등록 제목 코드의 접두(PY41)별 마지막으로 준 번호. 번호는 이 표의 한 줄을 +1 해서 받으므로 서버가 여러 개여도 겹치지 않는다."""
    __tablename__ = "problem_title_seq"
    prefix: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IntakeJob(Base):
    __tablename__ = "intake_job"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    maker_id: Mapped[str] = mapped_column(String, ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")   # processing | done | paused | failed
    input_kind: Mapped[str] = mapped_column(String(10), nullable=False)                      # 원본 | 엑셀 | 둘 다
    file_names: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    options: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)            # mode, auto_register
    records_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)                         # 중단·오류 안내
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # 처리 중인 워커가 문제마다 갱신


class IntakeCapture(Base):
    """원본 캡처: 올린 문서의 쪽 이미지(JPEG). 승인 화면 왼쪽에 원본을 그대로 보여 주는 데 쓰고, 보관 기간(기본 30일)이 지나면 지운다."""
    __tablename__ = "intake_capture"

    capture_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("intake_job.job_id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(String(40), nullable=False, default="image/jpeg")
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False, index=True)


class IntakeItem(Base):
    __tablename__ = "intake_item"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("intake_job.job_id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)            # 입력 순서
    out_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # 한 입력이 여러 문제로 나뉜 경우의 순번 (-1, -2 …)
    source_key: Mapped[str] = mapped_column(String, nullable=False)      # 입력 문제 이름(예: PY22-0001)
    record: Mapped[dict | None] = mapped_column(JsonType, nullable=True) # AI 에게 보낸 입력 (out_index 0 에만 저장)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING, index=True)
    result_id: Mapped[str | None] = mapped_column(String, nullable=True) # AI 결과의 id (예: PY22-0001-1)
    payload: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    review: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    check_fails: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    check_warns: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    approval_reasons: Mapped[list | None] = mapped_column(JsonType, nullable=True)   # 승인이 필요한 이유
    problem_id: Mapped[int | None] = mapped_column(Integer, nullable=True)           # 등록된(또는 이미 있던) 문제 ID
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)


# ====================================================================================================
# 문제 설명 저장 형식
# 문제 설명 저장 형식.
#
# 프론트는 문제 설명을 JSON 문자열 {"intent": 문제의도, "subtitle": 부제목, "content": 설명} 로 저장하고 설명 화면에서 세 칸으로 나눠 보여 준다.
# AI 는 payload.description 에 설명 본문만 쓰고(서버 검사·비교·중복 확인은 모두 이 본문 기준), 등록하는 순간에만 이 형식으로 감싼다.
# 부제목·문제의도는 엑셀(또는 원본)에 값이 있으면 그 값을, 없으면 AI 가 review.채움 에 적은 값을 쓴다. 둘 다 없으면 빈 문자열이다.
# ====================================================================================================

def unwrap(description):
    """이미 {"intent","subtitle","content"} 형식이면 (본문, 부제목, 문제의도), 아니면 None."""
    if not isinstance(description, str) or not description.lstrip().startswith("{"): return None
    try: d = json.loads(description)
    except ValueError: return None
    if not isinstance(d, dict) or "content" not in d: return None
    return str(d.get("content") or ""), str(d.get("subtitle") or ""), str(d.get("intent") or "")


def content_of(description):
    """중복 확인용: 감싸져 있으면 설명 본문만, 아니면 그대로."""
    u = unwrap(description)
    return u[0] if u else description


def _from_review(review, item):
    for f in (review or {}).get("채움") or []:
        if isinstance(f, dict) and f.get("항목") == item and str(f.get("내용") or "").strip():
            return str(f["내용"]).strip()
    return ""


def extras(record, review, name=""):
    """(부제목, 문제의도): 부제목은 입력의 부제목 > 원래 문제 이름(제목은 등록 코드로 바뀌므로) > AI 가 채운 키워드. 문제의도는 입력의 값 > AI 가 채운 값 > 빈 문자열."""
    fields = (record or {}).get("fields") or {}
    human = (review or {}).get("사람입력") or {}                              # 승인 화면에서 사람이 고친 값이 가장 우선
    sub = str(human.get("부제목") or "").strip() or str(fields.get("부제목") or "").strip() or str(name or "").strip() or _from_review(review, "부제목")
    intent = str(human.get("문제의도") or "").strip() or str(fields.get("문제의도") or "").strip() or _from_review(review, "문제의도")
    return sub, intent


def wrap(payload, record=None, review=None, name=""):
    """등록용 payload 사본: description 을 JSON 문자열로 감싼다. 이미 감싸져 있으면 그대로 둔다."""
    p = dict(payload)
    if unwrap(p.get("description")) is not None: return p
    sub, intent = extras(record, review, name)
    p["description"] = json.dumps({"intent": intent, "subtitle": sub, "content": p.get("description") or ""}, ensure_ascii=False)
    return p
