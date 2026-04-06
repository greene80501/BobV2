from abc import ABC, abstractmethod
from pathlib import Path


class SandboxRunner(ABC):
    """Abstract base class for sandbox runners."""

    @abstractmethod
    def wrap_command(self, cmd: list[str]) -> list[str]:
        """Wrap a command list with sandbox prefix args."""
        ...

    def available(self) -> bool:
        return True


class NoSandbox(SandboxRunner):
    """Pass-through sandbox that runs commands without any isolation."""

    def wrap_command(self, cmd: list[str]) -> list[str]:
        return cmd

    def available(self) -> bool:
        return True
