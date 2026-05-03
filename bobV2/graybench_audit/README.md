# GrayBench

**Open-source LLM benchmarking by [GrayArea Labs](https://www.grayarealabs.com/)).**

GrayBench is a reproducible benchmarking suite that measures how well large language models can write working code. Every benchmark run executes the LLM-generated code in an isolated environment and checks it against real test cases. The code, datasets, and evaluation logic are all open source so anyone can verify that published scores are real.

Currently supported benchmarks:

| Benchmark | Dataset | Tasks | What it tests |
|-----------|---------|-------|---------------|
| `qiskitbench` | [Qiskit/qiskit_humaneval](https://huggingface.co/datasets/Qiskit/qiskit_humaneval) | HumanEval for Qiskit (standard) | Basic quantum computing with Qiskit 2.0 |
| `qiskitbench-hard` | [Qiskit/qiskit_humaneval_hard](https://huggingface.co/datasets/Qiskit/qiskit_humaneval_hard) | HumanEval-Hard for Qiskit (advanced) | Complex quantum algorithms, transpilation, error correction |
| `critpt` | [CritPt-Benchmark/CritPt](https://huggingface.co/datasets/CritPt-Benchmark/CritPt) | 190 checkpoint tasks | Research-level physics (local execution only) |

---

## How It Works

1. GrayBench sends each task prompt to the LLM and asks it to write Python code.
2. The generated code is extracted from the response and combined with the task's test harness.
3. The combined script runs in an isolated virtual environment with the required packages (e.g. Qiskit 2.0.0).
4. A task passes only if the code executes without errors and all assertions in the test harness succeed.
5. Results (pass/fail, tokens, cost, timing) are stored in a local SQLite database.

No scores are self-reported by the model. Every result comes from actually running the code.

---

## Setup

**Requirements:** Python 3.11+

### 1. Install GrayBench

```bash
git clone https://github.com/grayarea-labs/graybench.git
cd graybench

python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install -e .
```

### 2. Set up the benchmark environment

Benchmarks execute LLM-generated code in a separate virtual environment with its own dependencies. This keeps benchmark packages (Qiskit, PyTorch, etc.) isolated from GrayBench itself.

```bash
graybench env setup qiskitbench
```

This creates `environments/qiskitbench/venv/` with Qiskit 2.0.0 and all required packages. It takes a few minutes and uses ~4GB of disk space.

For a minimal install (~500MB, no PyTorch/IBM cloud packages):

```bash
GRAYBENCH_QISKIT_MINIMAL=1 graybench env setup qiskitbench
```

You can verify the environment is working:

```bash
graybench env validate qiskitbench
```

### 3. Add an API key

```bash
graybench keys set google        # prompted for key securely
graybench keys test google       # verify it works
```

Supported providers: `google`, `openai`, `anthropic`, `deepseek`, `moonshot`, `openrouter`

### 4. (Optional) Add IBM Quantum key

Some QiskitBench tasks use `QiskitRuntimeService` which requires an IBM Quantum API token. Without this key, those tasks will fail but the rest of the benchmark will still run.

```bash
graybench keys set ibm_quantum
```

Get your token from [IBM Quantum](https://quantum.ibm.com/) under Account Settings > API Token. The key is stored encrypted and automatically injected as `QISKIT_IBM_TOKEN` when benchmark code runs.

---

## Usage

### Run a benchmark

```bash
# Qiskit HumanEval (standard)
graybench run qiskitbench -m google/gemini-2.5-flash

# Qiskit HumanEval-Hard (advanced)
graybench run qiskitbench-hard -m google/gemini-2.5-flash

# Run with parallel execution
graybench run qiskitbench-hard -m openai/gpt-4o --parallel 4

# Run a specific task by ID
graybench run qiskitbench-hard -m google/gemini-2.5-flash --task-id qiskit_hard_42

# Limit number of tasks
graybench run qiskitbench -m anthropic/claude-sonnet-4 --tasks 10
```

### View results

```bash
graybench results list                          # all runs
graybench results show <run_id>                 # detailed breakdown
graybench results compare <run_id_1> <run_id_2> # side-by-side
graybench results export <run_id> --format json # export
graybench results delete <run_id>               # remove a run
```

### Manage environments

```bash
graybench env list                  # show all environments
graybench env setup qiskitbench     # create/recreate
graybench env validate qiskitbench  # check it works
```

### Manage models and keys

```bash
graybench models list               # view model registry with pricing
graybench keys list                  # view configured keys (masked)
graybench keys set <provider>        # add/update a key
graybench keys test <provider>       # test a key
```

### Web dashboard

```bash
graybench server --port 8080
```

Opens a browser-based dashboard with run management, real-time progress, and result visualization.

---

## Model identifier format

Models are specified as `provider/model_id`:

```
google/gemini-2.5-flash
google/gemini-2.5-pro
openai/gpt-4o
openai/o1-preview
anthropic/claude-sonnet-4
anthropic/claude-opus-4
deepseek/deepseek-chat
openrouter/anthropic/claude-3-opus
```

---

## Project structure

```
graybench/
├── .venv/                          # main venv (graybench itself)
├── environments/
│   └── qiskitbench/
│       ├── venv/                   # isolated execution venv (Qiskit 2.0.0)
│       ├── requirements.txt        # pinned benchmark dependencies
│       └── metadata.json           # environment metadata
├── graybench/                      # source code
│   ├── cli.py                      # CLI (click-based)
│   ├── benchmarks/
│   │   ├── base.py                 # Benchmark base class
│   │   ├── runner.py               # parallel task runner
│   │   └── qiskitbench/            # Qiskit HumanEval benchmark
│   │       ├── benchmark.py        # benchmark definition
│   │       ├── dataset.py          # HuggingFace dataset loader
│   │       ├── evaluator.py        # code extraction + execution
│   │       └── environment.py      # QiskitEnvironment (venv config)
│   ├── environments/               # execution environment abstraction
│   │   ├── base.py                 # ExecutionEnvironment protocol
│   │   ├── venv_environment.py     # VenvEnvironment implementation
│   │   └── registry.py             # environment registry
│   ├── llm/                        # LLM provider abstraction
│   │   ├── registry.py             # provider factory
│   │   ├── google_provider.py
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── ...
│   ├── db/                         # SQLite persistence
│   └── web/                        # Flask web dashboard
├── data/
│   ├── graybench.db                # results database
│   └── datasets/                   # cached HuggingFace datasets
├── pyproject.toml
├── LICENSE
└── README.md
```

---

## Adding a new benchmark

1. Create a directory under `graybench/benchmarks/yourbench/`.
2. Implement `benchmark.py` extending `Benchmark`, with `load_tasks()` and `evaluate_task()`.
3. Create a dataset loader in `dataset.py`.
4. Optionally define an execution environment in `environment.py` if your benchmark needs specific packages.
5. Register with the `@register_benchmark` decorator.

---

## Contributing

Contributions are welcome. Please ensure tests pass and code follows the existing style.

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT

