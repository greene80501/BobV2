-- Research tracking columns for deeper analysis

-- benchmark_tasks: raw response, per-token breakdown, failure category
ALTER TABLE benchmark_tasks ADD COLUMN raw_llm_response TEXT;
ALTER TABLE benchmark_tasks ADD COLUMN input_tokens INTEGER DEFAULT 0;
ALTER TABLE benchmark_tasks ADD COLUMN output_tokens INTEGER DEFAULT 0;
ALTER TABLE benchmark_tasks ADD COLUMN cached_tokens INTEGER DEFAULT 0;
ALTER TABLE benchmark_tasks ADD COLUMN reasoning_tokens INTEGER DEFAULT 0;
ALTER TABLE benchmark_tasks ADD COLUMN failure_category TEXT;

-- benchmark_runs: environment info
ALTER TABLE benchmark_runs ADD COLUMN environment_json TEXT;
