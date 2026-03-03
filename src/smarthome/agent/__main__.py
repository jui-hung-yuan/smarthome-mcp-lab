"""CLI entry point: `uv run python -m smarthome.agent [--mock]`"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / ".smarthome" / ".env")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m smarthome.agent",
        description="Smart Home Agent — local-first, persistent memory",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock bulb instead of real hardware",
    )
    parser.add_argument(
        "--memory-dir",
        default=None,
        metavar="DIR",
        help="Directory for persistent memory (default: ~/.smarthome/memory)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model ID (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Import here so logging is configured first
    from smarthome.agent.config import AgentConfig
    from smarthome.agent.loop import AgentLoop
    from smarthome.agent.memory.embedder import OllamaEmbedder
    from smarthome.agent.memory.manager import MemoryManager
    from smarthome.agent.skill_loader import SkillLoader

    config = AgentConfig(
        model=args.model,
        mock=args.mock,
        **({"memory_dir": Path(args.memory_dir)} if args.memory_dir else {}),
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "Add it to ~/.smarthome/.env:\n"
            "  mkdir -p ~/.smarthome && echo 'ANTHROPIC_API_KEY=sk-...' >> ~/.smarthome/.env",
            file=sys.stderr,
        )
        sys.exit(1)

    memory = MemoryManager(
        memory_dir=config.memory_dir,
        embedder=OllamaEmbedder(base_url=config.ollama_url),
    )

    skills = SkillLoader(skills_dir=config.skills_dir)
    skills.load()

    # Pass mock flag to each skill that supports it
    for skill_name in skills.skill_names:
        skills.configure_skill(skill_name, mock=config.mock, config=config)

    loop = AgentLoop(config=config, memory=memory, skills=skills)
    await loop.run_session()


if __name__ == "__main__":
    asyncio.run(main())
