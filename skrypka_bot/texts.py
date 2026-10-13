"""Prompt text kept as files under prompts/."""

from importlib import resources


def prompt(name: str, **parts: str) -> str:
    """A file under prompts/, with {part} filled in; a backslash at a line end joins it to the next."""
    text = (resources.files(__package__) / "prompts" / name).read_text(encoding="utf-8").replace("\\\n", "")
    return text.format(**parts) if parts else text
