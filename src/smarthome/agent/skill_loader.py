"""SkillLoader: discovers skills from skills/*/SKILL.md and builds dispatch table."""

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str          # SKILL.md content after frontmatter
    module: ModuleType


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-like frontmatter from a Markdown file.

    Returns (fields_dict, body_after_frontmatter).
    Only handles simple key: value pairs (no nested YAML).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()

    body = text[m.end():]
    return fields, body


def _load_module(module_path: Path, name: str) -> ModuleType:
    """Dynamically import a Python file as a module."""
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SkillLoader:
    """Scans skills/*/SKILL.md, imports scripts/bulb.py (or any .py), builds dispatch."""

    def __init__(self, skills_dir: Path):
        self._skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        """Discover and load all skills. Call once at startup."""
        if not self._skills_dir.exists():
            logger.warning("Skills directory not found: %s", self._skills_dir)
            return

        for skill_md in sorted(self._skills_dir.glob("*/SKILL.md")):
            skill_dir = skill_md.parent
            try:
                self._load_skill(skill_dir, skill_md)
            except Exception as e:
                logger.error("Failed to load skill from %s: %s", skill_dir, e)

        logger.info("Loaded %d skill(s): %s", len(self._skills), list(self._skills.keys()))

    def _load_skill(self, skill_dir: Path, skill_md: Path) -> None:
        text = skill_md.read_text(encoding="utf-8")
        fields, body = _parse_frontmatter(text)

        name = fields.get("name") or skill_dir.name
        description = fields.get("description", "")

        # Find the first .py file in scripts/ (by convention)
        scripts_dir = skill_dir / "scripts"
        py_files = sorted(scripts_dir.glob("*.py")) if scripts_dir.exists() else []
        if not py_files:
            logger.warning("Skill '%s' has no Python scripts in %s", name, scripts_dir)
            return

        module_path = py_files[0]
        module_name = f"smarthome.agent.skills.{name.replace('-', '_')}"
        module = _load_module(module_path, module_name)

        if not hasattr(module, "execute"):
            logger.error("Skill '%s' (%s) does not expose execute(action, params)", name, module_path)
            return

        self._skills[name] = Skill(name=name, description=description, body=body, module=module)

    async def execute(self, skill_name: str, action: str, params: dict) -> dict:
        """Dispatch a tool call to the named skill."""
        skill = self._skills.get(skill_name)
        if skill is None:
            return {"success": False, "message": f"Unknown skill: {skill_name!r}. Available: {list(self._skills)}"}
        try:
            result = await skill.module.execute(action, params)
            return result
        except Exception as e:
            logger.error("Skill '%s' raised: %s", skill_name, e, exc_info=True)
            return {"success": False, "message": f"Skill error: {e}"}

    def build_system_prompt_section(self) -> str:
        """Return Level-1 skill index only (name + description).

        Full docs are intentionally omitted. Claude must call describe_skill(skill_name)
        before using a skill to load its actions, parameters, and examples.
        """
        if not self._skills:
            return ""

        lines = [
            "## Available Skills\n",
            "You can control devices and perform tasks by calling the `execute_skill` tool.",
            "Call `describe_skill(skill_name)` **once per skill per session** to load its full",
            "documentation. Docs are injected into your active context and persist for the whole",
            "session — do NOT call `describe_skill` again for the same skill.",
            "Do not guess parameters — describe first if docs are not yet in your context.\n",
            "| Skill | Description |",
            "|-------|-------------|",
        ]
        for skill in self._skills.values():
            lines.append(f"| `{skill.name}` | {skill.description} |")

        return "\n".join(lines)

    def describe_skill(self, skill_name: str) -> dict:
        """Return the full SKILL.md body for the named skill (synchronous, no I/O)."""
        skill = self._skills.get(skill_name)
        if skill is None:
            return {
                "success": False,
                "message": f"Unknown skill: {skill_name!r}. Available: {list(self._skills)}",
            }
        return {"success": True, "skill_name": skill_name, "docs": skill.body.strip()}

    def configure_skill(self, skill_name: str, **kwargs: object) -> None:
        """Pass runtime configuration to a skill's module (e.g. mock=True)."""
        skill = self._skills.get(skill_name)
        if skill and hasattr(skill.module, "configure"):
            skill.module.configure(**kwargs)

    @property
    def skill_names(self) -> list[str]:
        return list(self._skills.keys())
