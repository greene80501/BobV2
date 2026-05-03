"""Auto-classify task failures into categories for analysis."""

from typing import Optional
import re


def classify_failure(error: Optional[str], generated_code: Optional[str]) -> Optional[str]:
    """Classify a task failure into a category.

    Returns one of:
        "no_code"         – LLM produced no extractable code
        "syntax_error"    – Python syntax error
        "wrong_import"    – ImportError / ModuleNotFoundError
        "wrong_attribute" – AttributeError (wrong API usage)
        "undefined_name"  – NameError (undefined variable/function)
        "type_error"      – TypeError
        "assertion_error" – AssertionError (test failed)
        "timeout"         – Execution timed out
        "runtime_env"     – QiskitRuntimeService or backend errors
        "other"           – Uncategorised runtime error
        None              – Task passed (no failure)
    """
    if not error:
        return None

    err = error.lower()

    # No code extracted
    if not generated_code or "no extractable python code" in err:
        return "no_code"

    # Timeout
    if "timed out" in err or "timeout" in err:
        return "timeout"

    # Syntax errors
    if "syntaxerror" in err or "syntax error" in err:
        return "syntax_error"

    # Import errors
    if "importerror" in err or "modulenotfounderror" in err or "no module named" in err:
        return "wrong_import"

    # Attribute errors (wrong API calls)
    if "attributeerror" in err or "has no attribute" in err:
        return "wrong_attribute"

    # Name errors (undefined vars)
    if "nameerror" in err or "is not defined" in err:
        return "undefined_name"

    # Type errors
    if "typeerror" in err:
        return "type_error"

    # Assertion errors (test failures)
    if "assertionerror" in err or "assertion error" in err:
        return "assertion_error"

    # Qiskit runtime / backend errors
    if "qiskitruntimeservice" in err or "ibmbackend" in err or "ibm_runtime" in err:
        return "runtime_env"

    return "other"
