"""Light control skill — wraps smarthome.devices.TapoBulb / MockTapoBulb.

Exposes:
    execute(action: str, params: dict) -> dict
    configure(mock: bool, config: AgentConfig)  # optional, called by SkillLoader
"""

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path.home() / ".smarthome" / ".env")

logger = logging.getLogger(__name__)

# Module-level device instance (initialized on first execute or configure call)
_device = None
_mock: bool = False
_mock_state_file: Path = Path.home() / ".smarthome" / "tapo_bulb_state.json"


def configure(mock: bool = False, config: Any = None, **kwargs: Any) -> None:
    """Called by SkillLoader to inject runtime config before first use."""
    global _mock, _mock_state_file, _device
    _mock = mock
    if config is not None and hasattr(config, "mock_state_file"):
        _mock_state_file = config.mock_state_file
    # Reset device so it is re-created with new config
    _device = None


async def _get_device():
    """Lazy-init the bulb (real or mock)."""
    global _device

    if _device is not None:
        return _device

    if _mock:
        from smarthome.devices.tapo_bulb import MockTapoBulb
        _mock_state_file.parent.mkdir(parents=True, exist_ok=True)
        _device = MockTapoBulb(state_file=_mock_state_file)
        logger.info("Light-control skill using MockTapoBulb (state: %s)", _mock_state_file)
    else:
        tapo_user = os.environ.get("TAPO_USERNAME")
        tapo_pass = os.environ.get("TAPO_PASSWORD")
        tapo_ip = os.environ.get("TAPO_IP_ADDRESS")
        if not (tapo_user and tapo_pass and tapo_ip):
            raise RuntimeError(
                "Real bulb requires TAPO_USERNAME, TAPO_PASSWORD, and TAPO_IP_ADDRESS. "
                "Add them to ~/.smarthome/.env or run with --mock for testing."
            )
        from smarthome.devices.tapo_bulb import TapoBulb
        _device = await TapoBulb.connect(tapo_user, tapo_pass, tapo_ip)
        logger.info("Light-control skill connected to real TapoBulb at %s", tapo_ip)

    return _device


_DEFAULT_PALETTE = [
    ("Candlelight", "🕯️", "Cozy amber"),
    ("AliceBlue",   "💙", "Icy pale blue"),
    ("Lime",        "🟢", "Neon acid green"),
    ("BlueViolet",  "🟣", "Deep rich purple"),
]


def _parse_palette_from_user_md():
    """Parse ## Light Color Palette table from USER.md. Returns list of (name, emoji, mood) or None."""
    try:
        user_md = Path.home() / ".smarthome" / "memory" / "USER.md"
        if not user_md.exists():
            return None
        text = user_md.read_text()
        section = text.split("## Light Color Palette", 1)
        if len(section) < 2:
            return None
        rows = []
        past_header = False
        for line in section[1].splitlines():
            if not line.startswith("|"):
                continue
            # Separator row (e.g. |---|---|) — marks end of header
            if not set(line.replace("|", "").replace("-", "").replace(" ", "")):
                past_header = True
                continue
            if not past_header:
                continue  # skip header row
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4 and parts[1]:
                # New 4-column format: | # | Name | Emoji | Mood |
                rows.append((parts[1], parts[2], parts[3]))
            elif len(parts) >= 3 and parts[1]:
                # Old 3-column format: | # | Name | Mood |
                rows.append((parts[1], "💡", parts[2]))
        return rows if rows else None
    except Exception:
        return None


async def execute(action: str, params: dict) -> dict:
    """Execute a light-control action.

    Supported actions: turn_on, turn_off, set_brightness, set_color_temp, set_color,
                       show_palette, get_status
    """
    if action == "show_palette":
        palette = _parse_palette_from_user_md() or _DEFAULT_PALETTE
        blocks = [
            {
                "type": "actions",
                "elements": [{
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "Choose a color..."},
                    "action_id": "color_picker",
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": f"{emoji} {name}"},
                            "value": name,
                        }
                        for name, emoji, _ in palette
                    ],
                }],
            },
        ]
        return {
            "success": True,
            "message": "Color palette dropdown shown. Ask the user to select a color from the dropdown.",
            "_slack_blocks": blocks,
        }

    try:
        device = await _get_device()
    except RuntimeError as e:
        return {"success": False, "message": str(e)}
    return await device.execute(action, params)
