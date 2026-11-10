"""실제로 포트를 열어 띄우는 개발용 서버 (테스트 전용: 로그인은 가짜, DB 는 파일 SQLite).

    python dev_server.py [--port 8000] [--db dev.sqlite3] [--model 모델이름]

뜨면 http://127.0.0.1:8000/docs 에서 /intake/* 를 눌러 볼 수 있고, live_client.py 로 파일을 올려 끝까지 확인한다.
진짜 Noti 앱에서는 이 파일 대신 앱 main 에 include_router 를 붙인다 (deploy 안내 참고)."""
import argparse, asyncio, os, sys
import _bootstrap

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8000); ap.add_argument("--db", default="dev.sqlite3"); ap.add_argument("--model")
args = ap.parse_args()
_bootstrap.setup(sqlite=True)
if args.model: os.environ["LLM_MODEL"] = args.model
os.environ.setdefault("LLM_FALLBACK_MODEL", "")
os.environ.setdefault("INTAKE_MAX_FILES", "30")

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401,E401
from app.inputdata.intake import router as intake_router, service

engine = create_async_engine(f"sqlite+aiosqlite:///{os.path.abspath(args.db)}")
S = async_sessionmaker(engine)


async def _db():
    async with S() as db: yield db


app = FastAPI(title="Noti intake dev server")
app.include_router(intake_router.router)
app.dependency_overrides[get_db] = _db
app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}


@app.on_event("startup")
async def _startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with S() as db:
        await db.execute(text('INSERT OR IGNORE INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)


if __name__ == "__main__":
    print(f"개발 서버: http://127.0.0.1:{args.port}/docs  (DB: {os.path.abspath(args.db)}, 모델: {os.environ.get('LLM_MODEL') or '.env'})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
