"""등록 제목 코드(PY41_0007)용 번호 카운터 표 + 제목 유니크 인덱스 (Postgres).

Alembic 리비전으로 옮겨 쓰세요 (revision / down_revision 은 프로젝트 값으로 바꾸기).
이 마이그레이션을 적용하기 전에도 서버는 동작합니다 (번호를 '가장 큰 번호 + 1' 로 대신 매김. 서버가 여러 개면 겹칠 수 있음).

적용 전 확인 (코드 모양 제목이 이미 겹치면 유니크 인덱스를 만들 수 없습니다):

    SELECT title, count(*) FROM problem
    WHERE title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$'
    GROUP BY 1 HAVING count(*) > 1;
"""
import sqlalchemy as sa
from alembic import op

revision = "XXXX_title_seq"
down_revision = None   # TODO: 직전 리비전


def upgrade():
    op.create_table(
        "problem_title_seq",
        sa.Column("prefix", sa.String(40), primary_key=True),
        sa.Column("last_no", sa.Integer, nullable=False, server_default="0"),
    )
    # 이미 등록된 코드 제목의 가장 큰 번호에서 이어 가도록 접두별로 채운다
    op.execute("""
        INSERT INTO problem_title_seq (prefix, last_no)
        SELECT substring(title from '^([A-Z]+[0-9]+)_'), max(substring(title from '_([0-9]+)$')::int)
        FROM problem WHERE title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$'
        GROUP BY 1
    """)
    op.create_index("uq_problem_title_code", "problem", ["title"], unique=True,
                    postgresql_where=sa.text("title ~ '^[A-Z]+[0-9]+_[0-9]{4,}$'"))


def downgrade():
    op.drop_index("uq_problem_title_code", table_name="problem")
    op.drop_table("problem_title_seq")
