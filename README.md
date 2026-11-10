# Glowrium for Home Assistant

Control Glowrium C017 and C045 lights through a Glowrium cloud account, local Bluetooth, or both.

## Install

1. Copy `custom_components/glowrium` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services**, add **Glowrium**, and choose one or both setup options:
   - **Glowrium cloud account:** sign in with your email and password for remote control.
   - **Nearby Bluetooth light:** select a discovered C017 or C045 and confirm that it is yours. An account or internet connection is not required.

Bluetooth control requires a Home Assistant-supported adapter or an active ESPHome Bluetooth Proxy with a free connection slot. A passive scanner cannot control lights. Discovery does not connect to or control a light before you confirm it.

## Supported controls

| Model | Controls |
| --- | --- |
| C017 | Combined light on/off, main brightness, 2700–6500 K color temperature, scene presets, separate Main light and Mood light switches, Mood brightness, and Circadian rhythm. |
| C045 | On/off, brightness, HS color, six color-temperature presets (2000, 2700, 4000, 5000, 6500, and 7500 K), dynamic and music effects, and effect speed. Brightness is unavailable in music modes. |

## Connection notes

- When the same light is added through both options, it appears as one set of entities. Bluetooth is preferred; a linked cloud account can provide fallback if Bluetooth fails before a command is written.
- A Bluetooth-only light has no cloud fallback. Removing a cloud account does not remove a separately added Bluetooth light.
- Local Bluetooth access may not authenticate the client. Another nearby BLE client may be able to control the light. Disconnect the manufacturer app if it is using the light's Bluetooth connection.
- Setup reads the light's state; it does not activate, bind, reset, or update the device. A factory-reset light that needs activation must first be prepared with the manufacturer app.

## Troubleshooting

- If a Bluetooth light is not found, check the adapter or active proxy, connection slots, range, and whether another app is connected.
- If local control fails, download the Glowrium integration diagnostics to inspect the Bluetooth connection status and failure reason.
- If cloud control asks you to reconnect, sign in with the originally configured account.
