---
name: light-control
description: Control the TAPO L530E smart bulb — turn on/off, set brightness (1-100), set color temperature (2500-6500K).
---
# Light Control

## Actions

| Action | Params | Description |
|--------|--------|-------------|
| `turn_on` | none | Turn the bulb on |
| `turn_off` | none | Turn the bulb off |
| `set_brightness` | `brightness: int (1–100)` | Set brightness level |
| `set_color_temp` | `color_temp: int (2500–6500)` | Set color temperature in Kelvin |
| `set_color` | `color_name: str` | Set bulb to a named color (e.g. "Lime", "BlueViolet") |
| `show_palette` | none | Return color palette text + Slack dropdown buttons |
| `get_status` | none | Retrieve current bulb state |

## Usage

Call `execute_skill` with `skill_name="light-control"`, the desired `action`, and any required `params`.

### Examples

```
execute_skill(skill_name="light-control", action="turn_on", params={})
execute_skill(skill_name="light-control", action="set_brightness", params={"brightness": 30})
execute_skill(skill_name="light-control", action="set_color_temp", params={"color_temp": 3000})
execute_skill(skill_name="light-control", action="get_status", params={})
```

## Notes

- Brightness 1–30: dim / relaxed mood
- Brightness 70–100: bright / task lighting
- Color temp 2500–3000 K: warm white (evening / movie)
- Color temp 5000–6500 K: cool daylight (focus / morning)
- `set_color` and `set_color_temp` are mutually exclusive modes; using one clears the other

## Color Palette UX

When the user asks to change the bulb color or asks "what colors are available":
1. Call `execute_skill("light-control", "show_palette", {})` — it returns a formatted text list for you to relay, and automatically provides click buttons in Slack. Do not type the list manually.
2. Wait for the user to reply with a number or name.
3. Call `execute_skill("light-control", "set_color", {"color_name": "<name>"})` using the corresponding name.

If the user asks to add, remove, or replace a color in the palette, use `memory_write` to update the `## Light Color Palette` section in `USER.md`.
Table format: `| # | Name | Emoji | Mood |`
