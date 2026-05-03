"""Base protocol and types for execution environments.

Execution environments encapsulate the Python runtime and dependencies
needed to run benchmark-generated code safely and reproducibly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable


@dataclass
class ExecutionResult:
    """Result of executing code in an environment."""
    passed: bool
    stdout: str
    stderr: str
    returncode: int
    timeout: bool = False
    duration_s: float = 0.0


@runtime_checkable
class ExecutionEnvironment(Protocol):
    """Protocol for benchmark execution environments.
    
    Implementations provide isolated Python runtimes with specific
    package dependencies for running generated code safely.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique environment identifier (e.g., 'qiskitbench')."""
        ...
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        ...
    
    @abstractmethod
    def exists(self) -> bool:
        """Check if the environment is already set up."""
        ...
    
    @abstractmethod
    def ensure_exists(self) -> None:
        """Create the environment if it doesn't exist.
        
        Raises:
            RuntimeError: If setup fails.
        """
        ...
    
    @abstractmethod
    def get_python_executable(self) -> Path:
        """Return path to the Python executable in this environment."""
        ...
    
    @abstractmethod
    def run_code(
        self,
        code: str,
        timeout: int = 120,
        extra_args: Optional[list[str]] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute Python code in this environment.

        Args:
            code: Python code to execute
            timeout: Maximum execution time in seconds
            extra_args: Additional command line arguments
            env_vars: Extra environment variables to inject into the subprocess

        Returns:
            ExecutionResult with stdout, stderr, and status
        """
        ...
    
    @abstractmethod
    def validate(self) -> bool:
        """Validate that the environment is properly configured.
        
        Returns:
            True if environment is valid, False otherwise.
        """
        ...
    
    @abstractmethod
    def get_info(self) -> dict:
        """Get environment information for debugging/reproducibility.
        
        Returns:
            Dict with version info, package list, etc.
        """
        ...


class BaseEnvironment(ABC):
    """Base class for execution environments with common functionality."""
    
    def __init__(self, name: str, display_name: str):
        self._name = name
        self._display_name = display_name
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def display_name(self) -> str:
        return self._display_name
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
