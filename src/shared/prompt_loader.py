"""Load externalized prompt templates for AlphaDesk agents."""
from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

PROMPT_DIR = Path("prompts") / "agents"
SKILLS_DIR = Path("prompts") / "skills"


def load_prompt(agent_name: str, fallback: str = "", **variables: Any) -> str:
    path = PROMPT_DIR / f"{agent_name}.md"
    template_text = fallback

    if path.exists():
        template_text = path.read_text()
    elif fallback:
        log.debug("Prompt %s not found; using inline fallback", path)
    else:
        log.warning("Prompt %s not found and no fallback provided", path)
        return ""

    return Template(template_text).safe_substitute({k: _stringify(v) for k, v in variables.items()})


def load_skill(skill_name: str, **variables: Any) -> str:
    """Load a skill prompt from prompts/skills/.

    Args:
        skill_name: Name of the skill (without .md extension).
        **variables: Template variables to substitute.

    Returns:
        Rendered skill prompt, or empty string if not found.
    """
    path = SKILLS_DIR / f"{skill_name}.md"
    if not path.exists():
        log.debug("Skill prompt %s not found", path)
        return ""
    template_text = path.read_text()
    return Template(template_text).safe_substitute({k: _stringify(v) for k, v in variables.items()})


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    return str(value)
