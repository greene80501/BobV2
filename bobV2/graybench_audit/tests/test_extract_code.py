"""Tests for code extraction from LLM responses."""

from graybench.benchmarks.qiskitbench.evaluator import extract_code


def test_extracts_from_python_fence():
    response = "Here is the code:\n```python\nimport qiskit\nprint('hello')\n```\nDone."
    assert extract_code(response) == "import qiskit\nprint('hello')"


def test_extracts_from_plain_fence():
    response = "```\nimport qiskit\n```"
    assert extract_code(response) == "import qiskit"


def test_returns_last_fence():
    response = "```python\nfirst = 1\n```\n```python\nsecond = 2\n```"
    assert extract_code(response) == "second = 2"


def test_extracts_bare_code():
    response = "import qiskit\ndef foo():\n    return 1\n"
    result = extract_code(response)
    assert "import qiskit" in result
    assert "def foo():" in result


def test_bare_code_stops_at_natural_language():
    response = "import qiskit\ndef foo():\n    return 1\nThis function does something."
    result = extract_code(response)
    assert "This function does something" not in result
    assert "def foo():" in result


def test_returns_empty_for_no_code():
    response = "I cannot solve this problem. The answer is 42."
    assert extract_code(response) == ""


def test_returns_empty_for_latex():
    response = r"The eigenvalue is $\lambda = \frac{1}{2}$."
    assert extract_code(response) == ""


def test_returns_raw_if_starts_with_python():
    response = "import numpy as np\nx = np.array([1, 2, 3])"
    result = extract_code(response)
    assert "import numpy" in result
