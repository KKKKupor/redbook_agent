"""
Load system prompts from an agent's src/skills/ directory.

Each agent has its own skills/ folder:
    agents/{name}/src/skills/system.md   —  main system prompt
    agents/{name}/src/skills/style.md    —  (packager) style prompt
    ...

Usage:
    from utils.prompt_loader import load_skill
    prompt = load_skill(__file__, "system")      # loads system.md next to caller
    prompt = load_skill(__file__, "analysis")    # loads analysis.md
"""

from pathlib import Path

_cache = {}


def load_skill(caller_file: str, name: str) -> str:
    """Load a skill prompt from the caller's src/skills/{name}.md.

    Args:
        caller_file: pass __file__ from the calling module
        name: prompt file name without extension, e.g. 'system', 'style'

    Returns:
        The raw prompt text with placeholders intact.
    """
    skills_dir = Path(caller_file).resolve().parent / "skills"
    path = skills_dir / f"{name}.md"

    cache_key = str(path)
    if cache_key not in _cache:
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")
        _cache[cache_key] = path.read_text(encoding="utf-8")
    return _cache[cache_key]
