-- GrayBench database schema v1

-- API Keys (Fernet-encrypted)
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT NOT NULL,
    key_name        TEXT NOT NULL DEFAULT 'default',
    encrypted_key   BLOB NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE(provider, key_name)
);

-- Models registry with pricing
CREATE TABLE IF NOT EXISTS models (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider            TEXT NOT NULL,
    model_id            TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    input_price_per_m   REAL,
    cached_price_per_m  REAL,
    output_price_per_m  REAL,
    context_window      INTEGER,
    max_output_tokens   INTEGER,
    supports_json_mode  INTEGER NOT NULL DEFAULT 0,
    supports_reasoning  INTEGER NOT NULL DEFAULT 0,
    supports_tools      INTEGER NOT NULL DEFAULT 0,
    openrouter_id       TEXT,
    long_context_note   TEXT,
    batch_discount_pct  REAL,
    notes               TEXT,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider, model_id)
);

-- Benchmark runs
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL UNIQUE,
    benchmark       TEXT NOT NULL,
    model_provider  TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    route           TEXT NOT NULL DEFAULT 'direct',
    status          TEXT NOT NULL DEFAULT 'pending',
    config_json     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    completed_at    TEXT,
    error           TEXT,
    total_tasks     INTEGER DEFAULT 0,
    passed_tasks    INTEGER DEFAULT 0,
    failed_tasks    INTEGER DEFAULT 0,
    score           REAL,
    total_cost_usd  REAL DEFAULT 0.0,
    total_tokens    INTEGER DEFAULT 0,
    total_duration_s REAL DEFAULT 0.0
);

-- Per-task results
CREATE TABLE IF NOT EXISTS benchmark_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES benchmark_runs(run_id),
    task_id         TEXT NOT NULL,
    task_name       TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    started_at      TEXT,
    completed_at    TEXT,
    passed          INTEGER,
    score           REAL,
    attempts        INTEGER DEFAULT 0,
    error           TEXT,
    generated_code  TEXT,
    expected_output TEXT,
    actual_output   TEXT,
    tokens_used     INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    duration_s      REAL DEFAULT 0.0,
    metadata_json   TEXT,
    UNIQUE(run_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_status ON benchmark_runs(status);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_benchmark ON benchmark_runs(benchmark);
CREATE INDEX IF NOT EXISTS idx_benchmark_tasks_run_id ON benchmark_tasks(run_id);

-- Seed models data
INSERT OR IGNORE INTO models (provider, model_id, display_name, status, input_price_per_m, cached_price_per_m, output_price_per_m, supports_json_mode, supports_reasoning, supports_tools, openrouter_id, long_context_note, notes) VALUES
-- OpenAI
('openai', 'gpt-5.2', 'GPT-5.2', 'active', 1.75, 0.175, 14.0, 1, 0, 1, 'openai/gpt-5.2', NULL, NULL),
('openai', 'gpt-5.2-pro', 'GPT-5.2 Pro', 'active', 21.0, NULL, 168.0, 1, 1, 1, 'openai/gpt-5.2-pro', NULL, 'No caching available'),
('openai', 'gpt-5.1', 'GPT-5.1', 'active', 1.25, 0.125, 10.0, 1, 0, 1, 'openai/gpt-5.1', NULL, NULL),
('openai', 'gpt-5-mini', 'GPT-5 Mini', 'active', 0.25, 0.025, 2.0, 1, 0, 1, 'openai/gpt-5-mini', NULL, NULL),
('openai', 'gpt-5-nano', 'GPT-5 Nano', 'active', 0.05, 0.005, 0.4, 1, 0, 1, 'openai/gpt-5-nano', NULL, NULL),
('openai', 'gpt-4.1', 'GPT-4.1', 'active', 2.0, 0.5, 8.0, 1, 0, 1, 'openai/gpt-4.1', NULL, NULL),
('openai', 'gpt-4.1-mini', 'GPT-4.1 Mini', 'active', 0.4, 0.1, 1.6, 1, 0, 1, 'openai/gpt-4.1-mini', NULL, NULL),
('openai', 'gpt-4.1-nano', 'GPT-4.1 Nano', 'active', 0.1, 0.025, 0.4, 1, 0, 1, 'openai/gpt-4.1-nano', NULL, NULL),
('openai', 'gpt-4o', 'GPT-4o', 'active', 2.5, 1.25, 10.0, 1, 0, 1, 'openai/gpt-4o', NULL, NULL),
('openai', 'gpt-4o-mini', 'GPT-4o Mini', 'active', 0.15, 0.075, 0.6, 1, 0, 1, 'openai/gpt-4o-mini', NULL, NULL),
('openai', 'o3', 'o3', 'active', 2.0, 0.5, 8.0, 1, 1, 1, 'openai/o3', NULL, NULL),
('openai', 'o3-pro', 'o3 Pro', 'active', 20.0, NULL, 80.0, 1, 1, 1, 'openai/o3-pro', NULL, 'No caching available'),
('openai', 'o4-mini', 'o4-mini', 'active', 1.1, 0.275, 4.4, 1, 1, 1, 'openai/o4-mini', NULL, NULL),
('openai', 'o1', 'o1', 'active', 15.0, 7.5, 60.0, 1, 1, 1, 'openai/o1', NULL, NULL),
('openai', 'o1-mini', 'o1 Mini', 'active', 1.1, 0.55, 4.4, 1, 1, 1, 'openai/o1-mini', NULL, NULL),
('openai', 'o1-pro', 'o1 Pro', 'active', 150.0, NULL, 600.0, 1, 1, 1, 'openai/o1-pro', NULL, 'No caching available'),
-- Anthropic
('anthropic', 'claude-opus-4-5-20251101', 'Claude Opus 4.5', 'active', 5.0, 0.5, 25.0, 1, 0, 1, 'anthropic/claude-opus-4-5-20251101', NULL, NULL),
('anthropic', 'claude-sonnet-4-5-20250929', 'Claude Sonnet 4.5', 'active', 3.0, 0.3, 15.0, 1, 0, 1, 'anthropic/claude-sonnet-4-5-20250929', NULL, NULL),
('anthropic', 'claude-haiku-4-5-20251001', 'Claude Haiku 4.5', 'active', 1.0, 0.1, 5.0, 1, 0, 1, 'anthropic/claude-haiku-4-5-20251001', NULL, NULL),
('anthropic', 'claude-opus-4-1-20250805', 'Claude Opus 4.1', 'active', 15.0, 1.5, 75.0, 1, 0, 1, 'anthropic/claude-opus-4-1-20250805', NULL, NULL),
('anthropic', 'claude-opus-4-20250514', 'Claude Opus 4', 'active', 15.0, 1.5, 75.0, 1, 0, 1, 'anthropic/claude-opus-4-20250514', NULL, NULL),
('anthropic', 'claude-sonnet-4-20250514', 'Claude Sonnet 4', 'active', 3.0, 0.3, 15.0, 1, 0, 1, 'anthropic/claude-sonnet-4-20250514', NULL, NULL),
-- Google
('google', 'gemini-3-pro-preview', 'Gemini 3 Pro Preview', 'active', 2.0, 0.2, 12.0, 1, 1, 1, 'google/gemini-3-pro-preview', 'Input >200K tokens: $4.0/M. Output >200K tokens: $18.0/M.', NULL),
('google', 'gemini-3-flash-preview', 'Gemini 3 Flash Preview', 'active', 0.5, 0.05, 3.0, 1, 1, 1, 'google/gemini-3-flash-preview', NULL, 'No long-context surcharge'),
('google', 'gemini-2.5-pro', 'Gemini 2.5 Pro', 'active', 1.25, 0.125, 10.0, 1, 1, 1, 'google/gemini-2.5-pro', 'Input >200K tokens: $2.5/M. Output >200K tokens: $15.0/M.', NULL),
('google', 'gemini-2.5-flash', 'Gemini 2.5 Flash', 'active', 0.3, 0.03, 2.5, 1, 1, 1, 'google/gemini-2.5-flash', NULL, 'No long-context surcharge'),
('google', 'gemini-2.5-flash-lite', 'Gemini 2.5 Flash Lite', 'active', 0.1, 0.01, 0.8, 1, 0, 0, 'google/gemini-2.5-flash-lite', NULL, 'No long-context surcharge'),
-- DeepSeek
('deepseek', 'deepseek-chat', 'DeepSeek Chat', 'active', 0.28, 0.028, 0.42, 1, 0, 1, 'deepseek/deepseek-chat', NULL, 'Cached input ~10% of base rate'),
('deepseek', 'deepseek-reasoner', 'DeepSeek Reasoner', 'active', 0.28, 0.028, 0.42, 1, 1, 0, 'deepseek/deepseek-reasoner', NULL, 'Cached input ~10% of base rate'),
-- Moonshot
('moonshot', 'kimi-k2.5', 'Kimi K2.5', 'active', 0.6, 0.1, 3.0, 1, 0, 1, 'moonshot/kimi-k2.5', NULL, 'Cached input ~83% discount'),
('moonshot', 'kimi-k2-thinking', 'Kimi K2 Thinking', 'active', 0.6, 0.15, 2.5, 1, 1, 0, 'moonshot/kimi-k2-thinking', NULL, 'Cached input ~75% discount'),
('moonshot', 'kimi-k2-turbo-preview', 'Kimi K2 Turbo Preview', 'active', 1.15, 0.15, 8.0, 1, 1, 1, 'moonshot/kimi-k2-turbo-preview', NULL, 'Cached input ~87% discount');

-- Pricing notes (stored as a special model entry for reference)
INSERT OR IGNORE INTO models (provider, model_id, display_name, status, input_price_per_m, cached_price_per_m, output_price_per_m, notes) VALUES
('_system', '_pricing_notes', 'Pricing Notes', 'system', NULL, NULL, NULL,
'Long-Context Surcharges: Google Gemini models use tiered pricing based on context length. Gemini 3 Pro costs $2.0/M for <=200K tokens, $4.0/M above. Output beyond 200K: $18.0/M vs $12.0/M. Flash variants have no surcharge.

Cached Inputs: OpenAI/Anthropic ~90% discount on cached tokens. DeepSeek ~90% discount. Moonshot ~75-83% discount. Significant savings for repeated queries.

Batch Processing: OpenAI offers lower-cost Batch API. Anthropic Batch API gives ~50% off token costs.

Other: Anthropic Fast Mode for Opus 4.6 charges 6x base price. Google Gemini API web search grounding: $14 per 1K queries after free quota.');
