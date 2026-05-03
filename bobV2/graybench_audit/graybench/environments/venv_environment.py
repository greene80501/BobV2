"""Virtual environment-based execution environment."""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .base import BaseEnvironment, ExecutionResult

log = logging.getLogger(__name__)

# Base directory for all benchmark environments
_ENV_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "environments"


class VenvEnvironment(BaseEnvironment):
    """Execution environment based on Python venv.
    
    Each benchmark can define its own venv with specific package requirements.
    Environments are stored in environments/<benchmark_name>/venv/
    """
    
    def __init__(
        self,
        name: str,
        display_name: str,
        requirements: Optional[list[str]] = None,
        requirements_file: Optional[Path] = None,
        python_executable: Optional[str] = None,
    ):
        """Initialize a venv environment.
        
        Args:
            name: Unique environment identifier
            display_name: Human-readable name
            requirements: List of pip requirements (e.g., ["qiskit==2.0.0"])
            requirements_file: Path to requirements.txt file
            python_executable: Python executable to use for venv creation
        """
        super().__init__(name, display_name)
        self.requirements = requirements or []
        self.requirements_file = requirements_file
        self.python_executable = python_executable or sys.executable
        
        # Environment paths
        self.env_dir = _ENV_BASE_DIR / name
        self.venv_dir = self.env_dir / "venv"
        self.metadata_file = self.env_dir / "metadata.json"
        
        # Determine Python binary path (platform-aware)
        if os.name == "nt":  # Windows
            self.python_bin = self.venv_dir / "Scripts" / "python.exe"
        else:  # Unix/Linux/macOS
            self.python_bin = self.venv_dir / "bin" / "python"
    
    def exists(self) -> bool:
        """Check if the virtual environment exists and is valid."""
        return self.python_bin.exists() and self.metadata_file.exists()
    
    def ensure_exists(self) -> None:
        """Create the virtual environment if it doesn't exist."""
        if self.exists():
            log.info("Environment '%s' already exists at %s", self.name, self.venv_dir)
            return
        
        log.info("Creating environment '%s' at %s", self.name, self.venv_dir)
        self.env_dir.mkdir(parents=True, exist_ok=True)
        
        # Create venv
        try:
            self._create_venv()
            self._install_requirements()
            self._write_metadata()
            log.info("Environment '%s' created successfully", self.name)
        except Exception as e:
            # Clean up on failure
            if self.venv_dir.exists():
                import shutil
                shutil.rmtree(self.venv_dir)
            raise RuntimeError(f"Failed to create environment '{self.name}': {e}") from e
    
    def _create_venv(self) -> None:
        """Create the virtual environment."""
        log.info("Creating virtual environment with Python: %s", self.python_executable)
        result = subprocess.run(
            [self.python_executable, "-m", "venv", str(self.venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"venv creation failed: {result.stderr}")
    
    def _install_requirements(self) -> None:
        """Install packages into the venv."""
        pip_cmd = self._get_pip_cmd()
        
        # Upgrade pip first
        log.info("Upgrading pip...")
        subprocess.run(
            [pip_cmd, "install", "--upgrade", "pip"],
            capture_output=True,
            check=False,
        )
        
        # Install from requirements file if provided
        if self.requirements_file and self.requirements_file.exists():
            log.info("Installing from requirements file: %s", self.requirements_file)
            result = subprocess.run(
                [pip_cmd, "install", "-r", str(self.requirements_file)],
                capture_output=False,  # Show output for visibility
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("Failed to install requirements from file")
        
        # Install explicit requirements
        if self.requirements:
            log.info("Installing requirements: %s", self.requirements)
            result = subprocess.run(
                [pip_cmd, "install"] + self.requirements,
                capture_output=False,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("Failed to install requirements")
    
    def _write_metadata(self) -> None:
        """Write environment metadata for tracking."""
        metadata = {
            "name": self.name,
            "display_name": self.display_name,
            "python_executable": self.python_executable,
            "requirements": self.requirements,
            "created_at": subprocess.check_output(
                ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                text=True
            ).strip() if os.name != "nt" else "",
        }
        self.metadata_file.write_text(json.dumps(metadata, indent=2))
    
    def _get_pip_cmd(self) -> str:
        """Get the pip command path."""
        if os.name == "nt":
            pip_path = self.venv_dir / "Scripts" / "pip.exe"
        else:
            pip_path = self.venv_dir / "bin" / "pip"
        return str(pip_path)
    
    def get_python_executable(self) -> Path:
        """Return path to the Python executable."""
        return self.python_bin
    
    def run_code(
        self,
        code: str,
        timeout: int = 120,
        extra_args: Optional[list[str]] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute Python code in the venv."""
        if not self.exists():
            raise RuntimeError(f"Environment '{self.name}' does not exist. Run setup first.")

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8"
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            import time
            start = time.monotonic()

            cmd = [str(self.python_bin), script_path]
            if extra_args:
                cmd.extend(extra_args)

            sub_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            if env_vars:
                sub_env.update(env_vars)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=sub_env,
            )
            
            duration = time.monotonic() - start
            
            return ExecutionResult(
                passed=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
                duration_s=duration,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                passed=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                returncode=-1,
                timeout=True,
                duration_s=timeout,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass
    
    def validate(self) -> bool:
        """Validate the environment is working."""
        if not self.exists():
            return False
        
        try:
            # Try to run a simple Python command
            result = subprocess.run(
                [str(self.python_bin), "-c", "print('OK')"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and "OK" in result.stdout
        except Exception:
            return False
    
    def get_info(self) -> dict:
        """Get environment information."""
        info = {
            "name": self.name,
            "display_name": self.display_name,
            "venv_path": str(self.venv_dir),
            "python_executable": str(self.python_bin),
            "exists": self.exists(),
            "valid": self.validate() if self.exists() else False,
        }
        
        if self.metadata_file.exists():
            try:
                metadata = json.loads(self.metadata_file.read_text())
                info["metadata"] = metadata
            except Exception:
                pass
        
        # Try to get pip list if environment exists
        if self.exists():
            try:
                result = subprocess.run(
                    [self._get_pip_cmd(), "list", "--format=json"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    info["packages"] = json.loads(result.stdout)
            except Exception:
                pass
        
        return info
    
    def destroy(self) -> None:
        """Remove the environment completely."""
        import shutil
        if self.venv_dir.exists():
            shutil.rmtree(self.venv_dir)
        if self.metadata_file.exists():
            self.metadata_file.unlink()
        log.info("Environment '%s' destroyed", self.name)


class SystemPythonEnvironment(BaseEnvironment):
    """Execution environment using system Python (no isolation).
    
    Used for benchmarks that don't need special packages.
    """
    
    def __init__(self):
        super().__init__("system", "System Python")
        self.python_bin = Path(sys.executable)
    
    def exists(self) -> bool:
        return self.python_bin.exists()
    
    def ensure_exists(self) -> None:
        # Nothing to set up for system Python
        pass
    
    def get_python_executable(self) -> Path:
        return self.python_bin
    
    def run_code(
        self,
        code: str,
        timeout: int = 120,
        extra_args: Optional[list[str]] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute code using system Python."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8"
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            import time
            start = time.monotonic()

            cmd = [str(self.python_bin), script_path]
            if extra_args:
                cmd.extend(extra_args)

            sub_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            if env_vars:
                sub_env.update(env_vars)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=sub_env,
            )
            
            duration = time.monotonic() - start
            
            return ExecutionResult(
                passed=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
                duration_s=duration,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                passed=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                returncode=-1,
                timeout=True,
                duration_s=timeout,
            )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass
    
    def validate(self) -> bool:
        try:
            result = subprocess.run(
                [str(self.python_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_info(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "python_executable": str(self.python_bin),
            "exists": self.exists(),
            "valid": self.validate(),
        }


# Singleton for system Python
SYSTEM_PYTHON = SystemPythonEnvironment()
