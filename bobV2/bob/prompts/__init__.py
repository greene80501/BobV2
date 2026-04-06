from pathlib import Path


def load_system_prompt() -> str:
    """Load the base system prompt from system.md."""
    prompt_file = Path(__file__).parent / "system.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return (
        "You are bob, Your AI-Powered Development Partner. "
        "You are a coding agent running in the bob CLI. "
        "Be precise, safe, and helpful."
    )
