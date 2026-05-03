"""Environment registry for discovering and managing execution environments.

Environments can be registered by:
1. Direct registration in code
2. Auto-discovery from benchmark modules
3. Configuration files
"""

import logging
from typing import Optional

from .base import ExecutionEnvironment
from .venv_environment import VenvEnvironment

log = logging.getLogger(__name__)

# Registry of known environments
_ENVIRONMENTS: dict[str, type[ExecutionEnvironment]] = {}


def register_environment(name: str, env_class: type[ExecutionEnvironment]) -> None:
    """Register an environment class by name.
    
    Args:
        name: Unique environment identifier
        env_class: The environment class (not instance)
    """
    _ENVIRONMENTS[name] = env_class
    log.debug("Registered environment: %s", name)


def get_environment(name: str, **kwargs) -> ExecutionEnvironment:
    """Get an environment instance by name.
    
    Args:
        name: Environment identifier
        **kwargs: Arguments to pass to environment constructor
        
    Returns:
        Configured environment instance
        
    Raises:
        ValueError: If environment not found
    """
    if name in _ENVIRONMENTS:
        return _ENVIRONMENTS[name](**kwargs)
    
    # Try to auto-discover from benchmarks
    _try_discover_environments()
    
    if name in _ENVIRONMENTS:
        return _ENVIRONMENTS[name](**kwargs)
    
    available = ", ".join(sorted(_ENVIRONMENTS.keys()))
    raise ValueError(f"Unknown environment '{name}'. Available: {available}")


def list_environments() -> list[str]:
    """List all registered environment names."""
    _try_discover_environments()
    return sorted(_ENVIRONMENTS.keys())


def _try_discover_environments() -> None:
    """Try to discover environments from benchmark modules."""
    # Import benchmark modules to trigger their environment registrations
    try:
        from graybench.benchmarks import qiskitbench
        # The module import should register its environment
    except ImportError:
        pass
    
    try:
        from graybench.benchmarks import critpt
    except ImportError:
        pass


def get_environment_for_benchmark(benchmark_name: str) -> Optional[ExecutionEnvironment]:
    """Get the default environment for a benchmark.
    
    This looks for an environment with the same name as the benchmark,
    or returns None to use system Python.
    
    Args:
        benchmark_name: Name of the benchmark
        
    Returns:
        Environment instance, or None for system Python
    """
    # Try exact match first
    try:
        return get_environment(benchmark_name)
    except ValueError:
        pass
    
    # Try variations
    variations = [
        benchmark_name.replace("-", "_"),
        benchmark_name.replace("_", "-"),
        benchmark_name.split("-")[0],  # e.g., "qiskitbench-hard" -> "qiskitbench"
    ]
    
    for variant in variations:
        try:
            return get_environment(variant)
        except ValueError:
            continue
    
    return None


# Register built-in environments
from .venv_environment import SYSTEM_PYTHON


def setup_all_environments() -> None:
    """Ensure all registered environments are set up."""
    for name in list_environments():
        try:
            env = get_environment(name)
            env.ensure_exists()
        except Exception as e:
            log.error("Failed to setup environment '%s': %s", name, e)


def get_environment_info() -> dict:
    """Get information about all environments."""
    info = {}
    for name in list_environments():
        try:
            env = get_environment(name)
            info[name] = env.get_info()
        except Exception as e:
            info[name] = {"error": str(e)}
    return info
