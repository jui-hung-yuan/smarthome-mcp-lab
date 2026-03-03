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
