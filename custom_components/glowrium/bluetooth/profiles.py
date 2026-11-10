"""Model-specific CBOR codecs derived from the GlowriumX attribute dictionaries."""

from __future__ import annotations

import colorsys
import json
from pathlib import Path
from typing import Any

import cbor2

from ..const import MODEL_C017, MODEL_C045

with Path(__file__).with_name("presets.json").open(encoding="utf-8") as preset_file:
    PRESETS = json.load(preset_file)

C017_EFFECTS = {
    "LightMode.Reading": 2,
    "LightMode.Relax": 3,
    "LightMode.Sleep": 4,
    "LightMode.Movie": 5,
    "LightMode.Mood": 6,
    "LightMode.HappyTherapy": 8,
    "LightMode.Live": 9,
    "LightMode.MakeUp": 10,
    "LightMode.WakeUp": 11,
    "LightMode.Focus": 12,
    "LightMode.Study": 13,
    "LightMode.Guard": 14,
    "LightMode.Lightning": 15,
}
C017_SCENE_TEMPERATURE = {
    2: (67, 2),
    3: (68, 1),
    5: (70, 1),
    9: (72, 1),
    10: (73, 1),
    12: (74, 1),
    14: (75, 1),
}
KELVINS_C045 = (2000, 2700, 4000, 5000, 6500, 7500)
COLORS_C045 = (
    (255, 120, 11, 255),
    (255, 173, 94, 255),
    (255, 255, 150, 255),
    (255, 255, 200, 255),
    (255, 255, 255, 240),
    (255, 255, 255, 200),
)


class UnsupportedCommand(ValueError):
    """The command is invalid for this model or its current mode."""


class DeviceProfile:
    """Retain raw attribute state so partial notifications merge correctly."""

    def __init__(self, product: str) -> None:
        if product not in (MODEL_C017, MODEL_C045):
            raise ValueError("Unsupported model")
        self.product = product
        self.raw: dict[int, Any] = {}

    @property
    def effects(self) -> list[str]:
        return (
            list(C017_EFFECTS)
            if self.product == MODEL_C017
            else sorted(PRESETS["c045"])
        )

    def state_requests(self) -> list[bytes]:
        if self.product == MODEL_C017:
            keys = [1, 2, 7, 8, 9, 10, 14, 15, 23, 24, 67, 68, 70, 72, 73, 74, 75, 101]
            return [cbor2.dumps(keys[i : i + 10]) for i in range(0, len(keys), 10)]
        # Keep requested response sizes below the App's 200-byte limit.
        return [bytes([1, 2, 19, 22, 23, 101]), bytes([24])]

    @property
    def ready(self) -> bool:
        required = (
            {1, 7, 8, 9, 10, 15, 23, 24}
            if self.product == MODEL_C017
            else {1, 2, 19, 22, 24}
        )
        return required <= self.raw.keys()

    def update(self, payload: bytes) -> dict[str, Any]:
        decoded = cbor2.loads(payload)
        if not isinstance(decoded, dict) or any(
            type(key) is not int for key in decoded
        ):
            raise ValueError("Expected a CBOR map with integer attribute keys")
        # Validate known types before updating the retained state.
        scalar = {1, 2, 7, 8, 9, 10, 14, 15, 23, 24, 101}
        arrays: dict[int, int] = {67: 3, 68: 2, 70: 2, 72: 2, 73: 2, 74: 2, 75: 5}
        if self.product == MODEL_C045:
            scalar = {1, 2, 101}
            arrays = {19: 3, 22: 80, 23: 20, 24: 100}
        for key, value in decoded.items():
            if key in scalar and not isinstance(value, (int, bool)):
                raise ValueError("Invalid scalar attribute")
            if key in arrays and (
                not isinstance(value, (bytes, list, tuple))
                or len(value) != arrays[key]
                or any(
                    type(item) is not int
                    or not 0
                    <= item
                    <= (255 if self.product == MODEL_C045 else 0xFFFFFFFF)
                    for item in value
                )
            ):
                raise ValueError("Invalid byte-array attribute")
        self.raw.update(decoded)
        return self.normalized()

    def normalized(self) -> dict[str, Any]:
        r = self.raw
        if self.product == MODEL_C017:
            scale = r.get(15, 0)
            scene = r.get(7)
            if r.get(1) == 1 and scene in C017_SCENE_TEMPERATURE:
                key, index = C017_SCENE_TEMPERATURE[scene]
                if key in r:
                    scale = r[key][index]
            kelvin = min(
                PRESETS["c017_temperature"], key=lambda row: abs(row[1] - scale)
            )[0]
            return {
                "power": bool(r.get(8) or r.get(23)),
                "mainPower": bool(r.get(8)),
                "auxiliaryPower": bool(r.get(23)),
                "brightness": r.get(10, 0),
                "auxiliaryBrightness": r.get(24, 0),
                "colorTemperature": kelvin,
                "colorMode": "color_temp",
                "rhythm": bool(r.get(9)),
                "effect": next(
                    (
                        key
                        for key, value in C017_EFFECTS.items()
                        if value == scene and r.get(1) == 1
                    ),
                    None,
                ),
            }
        mode = list(r.get(19, []))
        dynamic = list(r.get(24, []))
        state: dict[str, Any] = {
            "power": bool(r.get(2)),
            "brightness": r.get(1, 0),
            "effect": next(
                (
                    key
                    for key, value in PRESETS["c045"].items()
                    if value["mode"] == mode
                ),
                None,
            ),
            "colorMode": "hs",
        }
        if len(mode) == 3 and mode[:2] == [0, 0] and mode[2] < 6:
            state.update(colorTemperature=KELVINS_C045[mode[2]], colorMode="color_temp")
        if len(dynamic) == 100:
            state["effectSpeed"] = max(1, min(100, 101 - (dynamic[2] & 0x7F)))
            if mode and mode[0] == 1:
                state["brightness"] = dynamic[3]
        if mode[:2] == [2, 0]:
            state["brightness"] = 100
        section = r.get(22)
        if section:
            red, green, blue, yellow = section[:4]
            hue, saturation, value = colorsys.rgb_to_hsv(
                min(255, red + yellow // 2) / 255,
                min(255, green + yellow // 2) / 255,
                blue / 255,
            )
            state.update(
                colorHue=hue * 360, colorSaturation=saturation, colorBrightness=value
            )
        return state

    def command(self, command: str, **values: Any) -> bytes:
        """Encode absolute, idempotent commands only; retries cannot toggle twice."""
        return cbor2.dumps(self.command_attributes(command, **values))

    def command_attributes(self, command: str, **values: Any) -> dict[int, Any]:
        """Return the attributes that must be observed after a control write."""
        attrs = (
            self._c017(command, values)
            if self.product == MODEL_C017
            else self._c045(command, values)
        )
        return attrs

    def confirms(self, attributes: dict[int, Any]) -> bool:
        """Only a notification or readback can confirm that a write took effect."""
        return all(
            key in self.raw
            and (
                list(self.raw[key]) == list(value)
                if isinstance(value, (bytes, list, tuple))
                else self.raw[key] == value
            )
            for key, value in attributes.items()
        )

    @staticmethod
    def _percent(value: Any) -> int:
        result = int(value)
        if not 0 <= result <= 100:
            raise UnsupportedCommand("Value must be between 0 and 100")
        return result

    def _c017(self, command: str, values: dict) -> dict[int, Any]:
        target = values.get("target", "main")
        if target not in ("main", "auxiliary", "all"):
            raise UnsupportedCommand(f"Unsupported C017 target: {target}")
        auxiliary = target == "auxiliary"
        power_key = 23 if auxiliary else 8
        if command in ("turn_on", "turn_off"):
            if target == "all":
                value = command == "turn_on"
                return {8: value, 23: value}
            return {power_key: command == "turn_on"}
        if command == "set_brightness":
            return {
                power_key: True,
                (24 if auxiliary else 10): self._percent(values["brightness"]),
            }
        if command == "set_rhythm":
            return {9: bool(values["power"])}
        if command == "set_color_temperature":
            scale = min(
                PRESETS["c017_temperature"],
                key=lambda row: abs(row[0] - int(values["colorTemperature"])),
            )[1]
            if self.raw.get(1) == 1:
                scene = self.raw.get(7)
                if scene not in C017_SCENE_TEMPERATURE:
                    raise UnsupportedCommand(
                        "Color temperature is unavailable in this effect"
                    )
                key, index = C017_SCENE_TEMPERATURE[scene]
                if key not in self.raw:
                    raise UnsupportedCommand(
                        "Read scene configuration before editing temperature"
                    )
                data = list(self.raw[key])
                data[index] = scale
                return {key: bytes(data) if isinstance(self.raw[key], bytes) else data}
            return {8: True, 23: True, 15: scale}
        if command == "set_effect" and values.get("effect") in C017_EFFECTS:
            return {1: 1, 7: C017_EFFECTS[values["effect"]]}
        raise UnsupportedCommand(f"Unsupported C017 command: {command}")

    def _dynamic(self) -> list[int]:
        data = list(self.raw.get(24, []))
        if len(data) != 100:
            raise UnsupportedCommand("Read dynamic effect state before editing it")
        return data

    def _c045(self, command: str, values: dict) -> dict[int, Any]:
        if command in ("turn_on", "turn_off"):
            return {2: command == "turn_on"}
        if command == "set_brightness":
            level = self._percent(values["brightness"])
            mode = list(self.raw.get(19, []))
            if mode[:2] == [2, 0]:
                raise UnsupportedCommand("Brightness is unavailable in music mode")
            result = {2: True, 1: level}
            if mode and mode[0] == 1:
                dynamic = self._dynamic()
                dynamic[3] = level
                result[24] = bytes(dynamic)
            return result
        if command == "set_color":
            hue, saturation = float(values["hue"]), float(values["saturation"])
            brightness = float(values.get("colorBrightness", 1))
            if not (0 <= hue <= 360 and 0 <= saturation <= 1 and 0 <= brightness <= 1):
                raise UnsupportedCommand("Invalid HS color")
            rgb = [
                int(channel * 255)
                for channel in colorsys.hsv_to_rgb(hue / 360, saturation, brightness)
            ]
            yellow = int(min(rgb[0], rgb[1]) * 0.5)
            pixel = [rgb[0] - yellow, rgb[1] - yellow, rgb[2], yellow * 2]
            return {2: True, 22: bytes(pixel * 20), 19: bytes([0, 0, 128])}
        if command == "set_color_temperature":
            kelvin = int(values["colorTemperature"])
            index = min(
                range(6),
                key=lambda i: (abs(KELVINS_C045[i] - kelvin), -KELVINS_C045[i]),
            )
            return {
                2: True,
                22: bytes(COLORS_C045[index] * 20),
                23: bytes([100] * 20),
                19: bytes([0, 0, index]),
            }
        if command == "set_effect" and values.get("effect") in PRESETS["c045"]:
            preset = PRESETS["c045"][values["effect"]]
            return {19: bytes(preset["mode"]), 24: bytes(preset["data"])}
        if command == "set_effect_speed":
            mode = list(self.raw.get(19, []))
            if not mode or mode[0] == 0:
                raise UnsupportedCommand("Select an effect before adjusting its speed")
            dynamic = self._dynamic()
            dynamic[2] = (dynamic[2] & 0x80) | (
                101 - max(1, self._percent(values["speed"]))
            )
            return {24: bytes(dynamic)}
        raise UnsupportedCommand(f"Unsupported C045 command: {command}")
