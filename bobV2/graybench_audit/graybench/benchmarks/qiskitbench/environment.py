"""QiskitBench execution environment.

Provides an isolated Python environment with Qiskit 2.0.0 and related
packages for executing quantum computing code safely.
"""

from pathlib import Path

from graybench.environments import VenvEnvironment, register_environment


class QiskitEnvironment(VenvEnvironment):
    """Execution environment for QiskitBench.
    
    Includes Qiskit 2.0.0 and all related packages for comprehensive
    quantum computing tasks. Uses an isolated venv to avoid conflicts.
    
    Note: This environment requires ~4GB disk space due to PyTorch and
    NVIDIA CUDA packages. For a minimal environment (~500MB), set:
        GRAYBENCH_QISKIT_MINIMAL=1
    """
    
    # Full requirements for complete Qiskit functionality
    REQUIREMENTS = [
        # HuggingFace / Evaluation
        "transformers>=4.25.1",
        "accelerate>=0.13.2",
        "datasets>=2.6.1",
        "evaluate>=0.3.0",
        "huggingface_hub>=0.11.1",
        # Code evaluation utilities
        "pyext==0.7",
        "mosestokenizer==1.0.0",
        # Qiskit core
        "qiskit==2.0.0",
        "qiskit-aer==0.17.0",
        "qiskit-algorithms==0.3.1",
        # Qiskit IBM (for cloud backend support)
        "qiskit-ibm-provider==0.11.0",
        "qiskit-ibm-runtime==0.45.1",
        "qiskit-ibm-transpiler==0.11.0",
        # Qiskit extras
        "qiskit_qasm3_import==0.5.0",
        "qiskit_experiments==0.9.0",
        "pylatexenc==2.10",
        # Scientific / Visualization
        "numpy==2.2.4",
        "matplotlib==3.10.1",
        "seaborn==0.13.2",
        "networkx==3.3",
        # Interactive
        "ipython==8.27.0",
    ]
    
    # Minimal requirements (no torch, no IBM cloud, ~500MB)
    # Set GRAYBENCH_QISKIT_MINIMAL=1 to use this
    MINIMAL_REQUIREMENTS = [
        # Core Qiskit
        "qiskit==2.0.0",
        "qiskit-aer==0.17.0",
        "qiskit-algorithms==0.3.1",
        # Scientific essentials
        "numpy==2.2.4",
        "scipy",
        "sympy>=1.3",
        "matplotlib==3.10.1",
        "networkx==3.3",
        "pylatexenc==2.10",
    ]
    
    def __init__(self):
        import os
        
        # Use minimal packages if explicitly requested
        if os.environ.get("GRAYBENCH_QISKIT_MINIMAL"):
            requirements = self.MINIMAL_REQUIREMENTS
            display_suffix = " (Minimal)"
        else:
            requirements = self.REQUIREMENTS
            display_suffix = ""
        
        super().__init__(
            name="qiskitbench",
            display_name=f"QiskitBench Environment (Qiskit 2.0.0){display_suffix}",
            requirements=requirements,
        )
    
    def validate(self) -> bool:
        """Validate that Qiskit is properly installed and working."""
        if not super().validate():
            return False
        
        try:
            # Try to import qiskit and check version
            result = self.run_code(
                "import qiskit; print(f'qiskit:{qiskit.__version__}')",
                timeout=30,
            )
            if not result.passed:
                return False
            
            # Verify it's Qiskit 2.x
            output = result.stdout.strip()
            if "qiskit:2." not in output:
                return False
            
            return True
        except Exception:
            return False
    
    def get_info(self) -> dict:
        """Get detailed environment info including Qiskit version."""
        info = super().get_info()
        
        if self.exists():
            try:
                # Get Qiskit version
                result = self.run_code(
                    "import qiskit; print(qiskit.__version__)",
                    timeout=30,
                )
                if result.passed:
                    info["qiskit_version"] = result.stdout.strip()
                
                # Get all qiskit-related packages
                if "packages" in info:
                    qiskit_packages = [
                        pkg for pkg in info["packages"]
                        if pkg.get("name", "").startswith("qiskit")
                    ]
                    info["qiskit_packages"] = qiskit_packages
                
            except Exception as e:
                info["version_error"] = str(e)
        
        return info


# Register the environment
def _register():
    """Register the QiskitEnvironment."""
    try:
        register_environment("qiskitbench", QiskitEnvironment)
    except Exception:
        # Already registered or other error
        pass


_register()
