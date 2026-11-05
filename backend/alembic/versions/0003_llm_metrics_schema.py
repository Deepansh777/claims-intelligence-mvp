"""LLM usage metrics (methodology-docs/llm-usage-metrics.md), plus cache-write tokens.

Numbers only: no prompt or completion text. Not tied to chat retention.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TOKENS = """
    input_tokens bigint NOT NULL DEFAULT 0,
    cached_input_tokens bigint NOT NULL DEFAULT 0,
    cache_write_tokens bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    reasoning_tokens bigint NOT NULL DEFAULT 0,
    total_tokens bigint NOT NULL DEFAULT 0,
"""
TOKEN_SUMS = """
    sum(input_tokens) AS input_tokens, sum(cached_input_tokens) AS cached_input_tokens,
    sum(cache_write_tokens) AS cache_write_tokens, sum(output_tokens) AS output_tokens,
    sum(reasoning_tokens) AS reasoning_tokens, sum(total_tokens) AS total_tokens,
    sum(cost_usd) AS cost_usd
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA llm_metrics")
    op.execute("""
        CREATE TABLE llm_metrics.model_pricing (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            provider text NOT NULL,
            model text NOT NULL,
            input_per_1m numeric(12, 6) NOT NULL,
            cached_input_per_1m numeric(12, 6) NOT NULL,
            cache_write_per_1m numeric(12, 6) NOT NULL,
            output_per_1m numeric(12, 6) NOT NULL,
            effective_from timestamptz NOT NULL DEFAULT now(),
            effective_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX model_pricing_current ON llm_metrics.model_pricing (provider, model) "
        "WHERE effective_to IS NULL"
    )
    # OpenAI Standard tier, short context, checked 2026-11-05 (see experimental/question_to_sql.py).
    op.execute("""
        INSERT INTO llm_metrics.model_pricing
            (provider, model, input_per_1m, cached_input_per_1m, cache_write_per_1m, output_per_1m)
        VALUES ('openai', 'gpt-6.1-sol', 2.00, 0.10, 2.50, 10.00)
    """)
    op.execute(f"""
        CREATE TABLE llm_metrics.llm_runs (
            id uuid PRIMARY KEY,
            user_id text NOT NULL,
            conversation_id uuid,
            feature text NOT NULL,
            status text NOT NULL CHECK (status IN ('success', 'error', 'cancelled')),
            error_type text,
            started_at timestamptz NOT NULL,
            ended_at timestamptz,
            latency_ms integer,
            {TOKENS}
            cost_usd numeric(14, 6),
            attributes jsonb NOT NULL DEFAULT '{{}}',
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON llm_metrics.llm_runs (started_at)")
    op.execute("CREATE INDEX ON llm_metrics.llm_runs (user_id, started_at)")
    op.execute(f"""
        CREATE TABLE llm_metrics.llm_calls (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES llm_metrics.llm_runs ON DELETE CASCADE,
            node text,
            provider text NOT NULL,
            model text NOT NULL,
            status text NOT NULL CHECK (status IN ('success', 'error', 'cancelled')),
            finish_reason text,
            {TOKENS}
            input_cost_usd numeric(14, 6),
            output_cost_usd numeric(14, 6),
            cost_usd numeric(14, 6),
            pricing_id bigint REFERENCES llm_metrics.model_pricing,
            latency_ms integer,
            ttft_ms integer,
            started_at timestamptz NOT NULL,
            ended_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON llm_metrics.llm_calls (run_id)")
    op.execute("CREATE INDEX ON llm_metrics.llm_calls (started_at)")
    op.execute(f"""
        CREATE VIEW llm_metrics.v_daily_usage AS
        SELECT c.started_at::date AS day, r.feature, c.model,
               count(DISTINCT c.run_id) AS runs, count(*) AS calls,
               {TOKEN_SUMS.replace("sum(", "sum(c.")}
        FROM llm_metrics.llm_calls c JOIN llm_metrics.llm_runs r ON r.id = c.run_id
        GROUP BY 1, 2, 3
    """)
    op.execute(f"""
        CREATE VIEW llm_metrics.v_user_daily_usage AS
        SELECT started_at::date AS day, user_id, feature, count(*) AS runs, {TOKEN_SUMS}
        FROM llm_metrics.llm_runs
        GROUP BY 1, 2, 3
    """)
    op.execute("""
        CREATE VIEW llm_metrics.v_unpriced_calls AS
        SELECT * FROM llm_metrics.llm_calls WHERE cost_usd IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA llm_metrics CASCADE")
