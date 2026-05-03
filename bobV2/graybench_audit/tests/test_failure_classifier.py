"""Tests for failure classification logic."""

from graybench.benchmarks.failure_classifier import classify_failure


def test_no_error_returns_none():
    assert classify_failure(None, "code") is None
    assert classify_failure("", "code") is None


def test_no_code():
    assert classify_failure("no extractable python code", None) == "no_code"
    assert classify_failure("some error", None) == "no_code"
    assert classify_failure("some error", "") == "no_code"


def test_syntax_error():
    assert classify_failure("SyntaxError: invalid syntax", "code") == "syntax_error"


def test_wrong_import():
    assert classify_failure("ModuleNotFoundError: No module named 'foo'", "code") == "wrong_import"
    assert classify_failure("ImportError: cannot import name 'bar'", "code") == "wrong_import"


def test_wrong_attribute():
    assert classify_failure("AttributeError: 'QuantumCircuit' has no attribute 'x'", "code") == "wrong_attribute"


def test_undefined_name():
    assert classify_failure("NameError: name 'foo' is not defined", "code") == "undefined_name"


def test_type_error():
    assert classify_failure("TypeError: expected str, got int", "code") == "type_error"


def test_assertion_error():
    assert classify_failure("AssertionError", "code") == "assertion_error"
    assert classify_failure("AssertionError: 0 != 1", "code") == "assertion_error"


def test_timeout():
    assert classify_failure("Process timed out after 120s", "code") == "timeout"
    assert classify_failure("Timeout exceeded", "code") == "timeout"


def test_runtime_env():
    assert classify_failure("QiskitRuntimeService error", "code") == "runtime_env"


def test_other():
    assert classify_failure("ValueError: something went wrong", "code") == "other"
