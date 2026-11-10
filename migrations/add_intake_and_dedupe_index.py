"""문제지 업로드(intake) 테이블 + 문제 중복 유니크 인덱스.

Alembic 리비전으로 옮겨 쓰세요 (revision / down_revision 은 프로젝트 값으로 바꾸기).
주의: 유니크 인덱스를 만들기 전에 이미 중복된 (maker_id, content_hash)가 있으면 실패합니다. 아래 SQL 로 먼저 확인하세요.

    SELECT maker_id, temporary_field_str_2, count(*) FROM problem
    WHERE is_deleted = false AND temporary_field_str_2 IS NOT NULL
    GROUP BY 1, 2 HAVING count(*) > 1;
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "XXXX_intake"
down_revision = None   # TODO: 직전 리비전


def upgrade():
    op.create_table(
        "intake_job",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("maker_id", sa.String, sa.ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_kind", sa.String(10), nullable=False),
        sa.Column("file_names", postgresql.JSONB, nullable=False),
        sa.Column("options", postgresql.JSONB, nullable=False),
        sa.Column("records_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "intake_item",
        sa.Column("item_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("intake_job.job_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("out_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_key", sa.String, nullable=False),
        sa.Column("record", postgresql.JSONB),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("result_id", sa.String),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("review", postgresql.JSONB),
        sa.Column("check_fails", postgresql.JSONB),
        sa.Column("check_warns", postgresql.JSONB),
        sa.Column("approval_reasons", postgresql.JSONB),
        sa.Column("problem_id", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("edited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_problem_maker_content_hash", "problem", ["maker_id", "temporary_field_str_2"], unique=True,
        postgresql_where=sa.text("is_deleted = false AND temporary_field_str_2 IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_problem_maker_content_hash", table_name="problem")
    op.drop_table("intake_item")
    op.drop_table("intake_job")
