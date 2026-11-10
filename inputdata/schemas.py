# app/inputdata/schemas.py
from typing import List, Optional, Union, Literal, Any, Annotated
from pydantic import BaseModel, Field, field_validator, model_validator, TypeAdapter, ValidationError, ConfigDict, StringConstraints, AliasChoices
from enum import Enum
import json
import re

# --------- Enums ---------
class ProblemTypeEnum(str, Enum):
    coding = "코딩"
    debugging = "디버깅"
    multiple_choice = "객관식"
    short_answer = "단답형"
    subjective = "주관식"

class CodingRatingModeEnum(str, Enum):
    space = "space"
    regex = "regex"
    hard = "hard"
    none = "none"

class DebuggingRatingModeEnum(str, Enum):
    space = "space"
    regex = "regex"
    hard = "hard"
    none = "none"
 
class MultipleChoiceRatingModeEnum(str, Enum):
    none = "none"

class ShortAnswerRatingModeEnum(str, Enum):
    exact = "exact"
    partial = "partial"
    soft = "soft"
    none = "none"

class SubjectiveRatingModeEnum(str, Enum):
    active = "active"
    deactive = "deactive"

# --------- 공통 모델 ---------
def _norm_language(v):
    # 언어는 소문자로 통일 (기본값 python)
    if v is None:
        return "python"
    s = str(v).strip().lower()
    return s or "python"


class ReferenceCode(BaseModel):
    language: str = "python"
    code: str
    is_main: Optional[bool] = True

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, v):
        return _norm_language(v)

    @field_validator("code", mode="after")
    @classmethod
    def code_not_blank(cls, v):
        if not v.strip():
            raise ValueError("정답 코드는 비어 있을 수 없습니다.")
        return v


class TestCase(BaseModel):
    # 요청에서는 expected_output 과 output 둘 다 받고, 저장 키는 expected_output 으로 통일
    input: str = ""
    expected_output: str = Field(validation_alias=AliasChoices("expected_output", "output"))
    is_hidden: Optional[bool] = False

    # 입력이 없는 케이스: null 이 와도 빈 문자열로 처리
    @field_validator("input", mode="before")
    @classmethod
    def input_none_to_empty(cls, v):
        return "" if v is None else v


class BaseCode(BaseModel):
    language: str = "python"
    code: str
    is_main: Optional[bool] = False

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, v):
        return _norm_language(v)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DIFFICULTIES = {"easy", "medium", "hard"}


# --------- Base Problem ---------
class ProblemBaseRequest(BaseModel):
    title: NonEmptyStr          # 수정: 기존 `title: str = NonEmptyStr` 는 검증이 되지 않았음
    description: NonEmptyStr    # 수정: 위와 동일
    difficulty: Optional[str] = "easy"
    tags: List[str] = []
    problem_condition: List[str] = []
    grading_criteria: List[str] = []
    image_url: Optional[str] = None     # 문제 그림 주소. 올리기는 기존 /api/media/storage (presigned-url → confirm) 로 하고, 그 결과 url 을 여기에 넣는다

    @field_validator("image_url", mode="before")
    @classmethod
    def check_image_url(cls, v):
        if v is None: return None
        s = str(v).strip()
        if not s: return None
        if len(s) > 2000: raise ValueError("image_url 이 너무 깁니다.")
        if not re.match(r"^(https?://|/)", s): raise ValueError("image_url 은 http(s):// 또는 / 로 시작하는 주소여야 합니다.")
        return s

    # 대소문자 무시, easy/medium/hard 외의 값은 거부
    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, v):
        if v is None:
            return "easy"
        s = str(v).strip().lower()
        if not s:
            return "easy"
        if s not in DIFFICULTIES:
            raise ValueError("난이도는 easy, medium, hard 중 하나여야 합니다.")
        return s

    # 하위 클래스의 rating_mode 를 소문자로 정규화 (Regex -> regex)
    @field_validator("rating_mode", mode="before", check_fields=False)
    @classmethod
    def normalize_rating_mode(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


def _check_gradable(test_cases, problem_condition):
    # 테스트 케이스가 없는 문제(그래픽 출력 등)는 AI 채점 조건이 있어야 등록할 수 있음
    if not test_cases and not problem_condition:
        raise ValueError("테스트 케이스가 없으면 problem_condition(AI 채점 조건)이 최소 1개 필요합니다.")

# --------- Coding Problem ---------
class CodingProblemRequest(ProblemBaseRequest):
    problemType: Literal["코딩"]
    rating_mode: CodingRatingModeEnum = CodingRatingModeEnum.none
    test_cases: List[TestCase]      # 빈 목록 허용 (그래픽 출력 문제). 키 자체는 필수
    reference_codes: List[ReferenceCode] = Field(min_length=1)

    @model_validator(mode="after")
    def check_gradable(self):
        _check_gradable(self.test_cases, self.problem_condition)
        return self
    
    @field_validator("test_cases", mode="before")
    @classmethod
    def validate_test_cases(cls, v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    @field_validator("reference_codes", mode="before")
    @classmethod
    def validate_reference_codes(cls, v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

# --------- Debugging Problem ---------
class DebuggingProblemRequest(ProblemBaseRequest):
    problemType: Literal["디버깅"]
    rating_mode: DebuggingRatingModeEnum = DebuggingRatingModeEnum.none
    test_cases: List[TestCase]      # 빈 목록 허용 (그래픽 출력 문제). 키 자체는 필수
    base_code: List[BaseCode] = Field(min_length=1)
    reference_codes: List[ReferenceCode] = Field(min_length=1)

    @model_validator(mode="after")
    def check_gradable(self):
        _check_gradable(self.test_cases, self.problem_condition)
        return self

    # 코딩 문제와 동일하게 단일 객체/None 을 목록으로 보정
    @field_validator("reference_codes", mode="before")
    @classmethod
    def validate_reference_codes(cls, v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]
    
    @field_validator("test_cases", mode="before")
    @classmethod
    def validate_test_cases(cls, v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    @field_validator("base_code", mode="before")
    @classmethod
    def validate_base_code(cls, v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

# --------- Multiple Choice Problem ---------
class MultipleChoiceRequest(ProblemBaseRequest):
    problemType: Literal["객관식"]
    rating_mode: MultipleChoiceRatingModeEnum = MultipleChoiceRatingModeEnum.none
    options: List[str] = Field(min_length=2)
    correct_answers: List[int] = Field(min_length=1)
    
    @field_validator("options", mode="before")
    @classmethod
    def validate_options(cls, v):
        if v is None:
            return []
        # 보기에 ,가 들어오면 문항으로 나뉘어짐[예) 보기가 1,3인데 1과 3번으로 문항이 나뉘어짐]
        # if isinstance(v, str):
        #     return v.split(",") if v.strip() else []
        # return v if isinstance(v, list) else []
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except ValueError:
                    pass
            v = re.split(r"[|\n]", s)

        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
        return v

    @field_validator("correct_answers", mode="before")
    @classmethod
    def validate_correct_answers(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
        #     try:
        #         return [int(x.strip()) for x in v.split(",") if x.strip()]
        #     except ValueError:
        #         return []
        # if isinstance(v, list):
        #     return [int(x) for x in v if isinstance(x, (int, str))]
        # return []
        # 정답 형태가 달라도 동일하게 처리
            parts = [x.strip() for x in v.split(",") if x.strip()]
            try:
                return [int(x) for x in parts]
            except ValueError:
                return v
        if isinstance(v, (list, tuple)):
            return list(v)
        return v

    #정답 번호가 범위 안에 존재하는지 판단
    @model_validator(mode="after")
    def check_answers_in_range(self):
        n = len(self.options)
        # 0부터 시작 기준: 보기 4개면 0~3
        if any(a < 0 or a >= n for a in self.correct_answers):
            raise ValueError(f"정답 번호는 0~{n-1} 범위여야 합니다.")
        return self

# --------- Short Answer Problem ---------
class ShortAnswerProblemRequest(ProblemBaseRequest):
    problemType: Literal["단답형"]
    rating_mode: ShortAnswerRatingModeEnum = ShortAnswerRatingModeEnum.none
    answer_text: Union[List[str], dict[str, List[str]]] 
    
    # @field_validator("answer_text", mode="before")
    # @classmethod
    # def validate_answer_text(cls, v):
    #     if v is None:
    #         return []
    #     # 이미 dict이면 유지 (여러 정답 형식)
    #     if isinstance(v, dict):
    #         return v
    #     # 리스트면 유지
    #     if isinstance(v, list):
    #         return v
    #     # 문자열이면 그대로 반환
    #     if isinstance(v, str):
    #         return v
    #     return []
    # DB 형태 정규화
    @field_validator("answer_text", mode="before")
    @classmethod
    def normalize_answer_text(cls, v):
        if v is None:
            return []
        if isinstance(v, str):                
            s = v.strip()
            return [s] if s else []
        return v

    # 최소 정답이 한 개 텍스트가 존재하는지 확인(이전에는 빈 문자열이라도 처리함)
    @field_validator("answer_text", mode="after")
    @classmethod
    def check_not_empty(cls, v):
        if isinstance(v, dict):     # 딕셔너리 검증
            ok = any(str(a).strip() for answers in v.values() for a in answers)
        else:       # 리스트 검증
            ok = any(str(a).strip() for a in v)
        if not ok:
            raise ValueError("정답이 최소 1개 필요합니다.")
        return v

# --------- Subjective Problem ---------
class SubjectiveProblemRequest(ProblemBaseRequest):
    problemType: Literal["주관식"]
    rating_mode: SubjectiveRatingModeEnum = SubjectiveRatingModeEnum.deactive
    answer_text: str = Field(min_length=1)
    
    @field_validator("answer_text", mode="before")
    @classmethod
    def validate_answer_text(cls, v):
        if v is None:
            return ""
        # 리스트면 첫 번째 항목 사용
        if isinstance(v, list):
            return str(v[0]) if v else ""
        # 딕셔너리면 JSON 문자열로 변환
        if isinstance(v, dict):
            import json
            return json.dumps(v, ensure_ascii=False)
        return str(v)

# --------- Union Type ---------
# ProblemRequestUnion = Union[
#     CodingProblemRequest,
#     DebuggingProblemRequest,
#     MultipleChoiceRequest,
#     ShortAnswerProblemRequest,
#     SubjectiveProblemRequest,
# ]
# problemType으로 빠르게 분류
ProblemRequestUnion = Annotated[
    Union[
        CodingProblemRequest,
        DebuggingProblemRequest,
        MultipleChoiceRequest,
        ShortAnswerProblemRequest,
        SubjectiveProblemRequest,
    ],
    Field(discriminator="problemType"),
]

problem_adapter = TypeAdapter(ProblemRequestUnion)      # 딕셔너리로 저장된 문제들을 검사

# --------- Input Data Request ---------
# class InputDataRequest(BaseModel):
#     model_config = ConfigDict(use_enum_values=True)
#     problems: List[ProblemRequestUnion]
class InputDataRequest(BaseModel):
    # 개별 검증은 라우터에서 건별로 수행
    problems: List[dict[str, Any]] = Field(min_length=1, max_length=500)        # 여러 문제를 딕셔너리로 저장

# 에러나는 부분을 알려줌
def format_validation_errors(e: ValidationError) -> list[dict]:
    result = []
    for err in e.errors(include_url=False, include_context=False, include_input=False):
        # 첫 요소는 유형 태그. 필드 없이 모델 전체에서 난 오류는 "문제 전체"로 표시
        field = ".".join(map(str, err["loc"][1:])) if len(err["loc"]) > 1 else "문제 전체"
        result.append({"field": field, "message": err["msg"]})
    return result