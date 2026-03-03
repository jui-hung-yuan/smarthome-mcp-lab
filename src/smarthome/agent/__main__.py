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
        "--slack",
        action="store_true",
        help="Run Slack adapter instead of CLI REPL",
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

    if args.slack:
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        app_token = os.environ.get("SLACK_APP_TOKEN", "")
        signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")

        missing = [name for name, val in [
            ("SLACK_BOT_TOKEN", bot_token),
            ("SLACK_APP_TOKEN", app_token),
            ("SLACK_SIGNING_SECRET", signing_secret),
        ] if not val]
        if missing:
            print(
                f"Error: Missing Slack env vars: {', '.join(missing)}\n"
                "Add them to ~/.smarthome/.env",
                file=sys.stderr,
            )
            sys.exit(1)

        raw_allowed = os.environ.get("SLACK_ALLOWED_USERS", "")
        allowed_users = [u.strip() for u in raw_allowed.split(",") if u.strip()] or None

        from smarthome.agent.slack_adapter import SlackAdapter, SlackAdapterConfig

        slack_config = SlackAdapterConfig(
            bot_token=bot_token,
            app_token=app_token,
            signing_secret=signing_secret,
            allowed_users=allowed_users,
        )
        adapter = SlackAdapter(loop=loop, config=slack_config)
        print("Starting Slack adapter (Socket Mode)…")
        await adapter.start()
    else:
        await loop.run_session()


if __name__ == "__main__":
    asyncio.run(main())
