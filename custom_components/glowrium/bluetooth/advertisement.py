"""Parse the same service data as GlowriumX BleAdvertiseDataParser."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..const import MODEL_C017, MODEL_C045
from ..identity import hardware_key, normalize_mac

SCAN_UUID = "facebd00-0000-1000-8000-00805f9b34fb"
SERVICE_UUID = "facebd00-7261-6262-6974-696f74626c65"
WRITE_UUID = "facebd01-7261-6262-6974-696f74626c65"
STATE_UUID = "facebd02-7261-6262-6974-696f74626c65"
MODELS = {17: MODEL_C017, 45: MODEL_C045}


@dataclass(frozen=True)
class GlowriumAdvertisement:
    """Separate the advertised hardware MAC from the OS/proxy address."""

    address: str
    mac: str
    product_key: str
    pid: int
    sub_id: int
    firmware: int
    name: str

    @property
    def key(self) -> str:
        return hardware_key(self.mac, self.product_key)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_advertisement(info: Any) -> GlowriumAdvertisement | None:
    """Reject truncated packets and unsupported models, even with a brand name."""
    raw = next(
        (value for key, value in info.service_data.items() if key.lower() == SCAN_UUID),
        None,
    )
    if raw is None or len(raw) < 11:
        return None
    pid = int.from_bytes(raw[9:11], "big")
    mac = normalize_mac(bytes(raw[2:8]).hex())
    if pid not in MODELS or mac is None:
        return None
    return GlowriumAdvertisement(
        address=info.address,
        mac=mac,
        product_key=MODELS[pid],
        pid=pid,
        sub_id=raw[11] if len(raw) > 11 else 0,
        firmware=raw[8],
        name=info.name or f"Glowrium {mac[-6:]}",
    )
