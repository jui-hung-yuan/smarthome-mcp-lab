"""Tests for SkillLoader: discovery, dispatch, system prompt generation."""

import pytest

from smarthome.agent.skill_loader import SkillLoader


@pytest.fixture
def skills_dir(tmp_path):
    """Build a minimal skills directory with one test skill."""
    skill_dir = tmp_path / "skills" / "test-skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill for unit testing.\n"
        "---\n"
        "## Actions\n"
        "- echo — returns params unchanged\n"
    )

    (scripts_dir / "main.py").write_text(
        "async def execute(action, params):\n"
        "    if action == 'echo':\n"
        "        return {'success': True, 'echoed': params}\n"
        "    return {'success': False, 'message': f'Unknown action: {action}'}\n"
        "\n"
        "_config = {}\n"
        "\n"
        "def configure(**kwargs):\n"
        "    _config.update(kwargs)\n"
    )
    return tmp_path / "skills"


@pytest.fixture
def loader(skills_dir):
    sl = SkillLoader(skills_dir=skills_dir)
    sl.load()
    return sl


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_skill_names_discovered(loader):
    assert "test-skill" in loader.skill_names


def test_empty_skills_dir(tmp_path):
    empty = tmp_path / "empty-skills"
    empty.mkdir()
    sl = SkillLoader(skills_dir=empty)
    sl.load()
    assert sl.skill_names == []


def test_nonexistent_skills_dir(tmp_path):
    sl = SkillLoader(skills_dir=tmp_path / "does-not-exist")
    sl.load()  # should not raise
    assert sl.skill_names == []


def test_skill_without_scripts_is_skipped(tmp_path):
    skill_dir = tmp_path / "skills" / "no-script"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: no-script\ndescription: Has no scripts.\n---\n"
    )
    sl = SkillLoader(skills_dir=tmp_path / "skills")
    sl.load()
    assert "no-script" not in sl.skill_names


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def test_system_prompt_contains_skill_name(loader):
    prompt = loader.build_system_prompt_section()
    assert "test-skill" in prompt


def test_system_prompt_contains_description(loader):
    prompt = loader.build_system_prompt_section()
    assert "A test skill for unit testing" in prompt


def test_system_prompt_excludes_skill_body(loader):
    """Level 1: full body must NOT appear; only name + description are listed."""
    prompt = loader.build_system_prompt_section()
    assert "echo" not in prompt


def test_empty_loader_returns_empty_prompt(tmp_path):
    sl = SkillLoader(skills_dir=tmp_path / "no-skills")
    sl.load()
    assert sl.build_system_prompt_section() == ""


def test_system_prompt_contains_disclosure_instructions(loader):
    prompt = loader.build_system_prompt_section()
    assert "describe_skill" in prompt


def test_describe_skill_returns_body(loader):
    result = loader.describe_skill("test-skill")
    assert result["success"] is True
    assert result["skill_name"] == "test-skill"
    assert "echo" in result["docs"]


def test_describe_skill_unknown_returns_error(loader):
    result = loader.describe_skill("does-not-exist")
    assert result["success"] is False
    assert "does-not-exist" in result["message"]
    assert "test-skill" in result["message"]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_dispatches_to_skill(loader):
    result = await loader.execute("test-skill", "echo", {"key": "value"})
    assert result["success"] is True
    assert result["echoed"] == {"key": "value"}


@pytest.mark.asyncio
async def test_execute_unknown_skill_returns_error(loader):
    result = await loader.execute("nonexistent-skill", "action", {})
    assert result["success"] is False
    assert "Unknown skill" in result["message"]


@pytest.mark.asyncio
async def test_execute_unknown_action_handled_by_skill(loader):
    result = await loader.execute("test-skill", "unknown-action", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# configure()
# ---------------------------------------------------------------------------

def test_configure_calls_skill_configure(loader):
    # Should not raise; configure() is optional
    loader.configure_skill("test-skill", mock=True)