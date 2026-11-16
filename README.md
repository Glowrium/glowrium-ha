# Glowrium for Home Assistant

Control H1 and H4 lights through your Glowrium cloud account, local Bluetooth, or both.

## Install

1. Copy `custom_components/glowrium` to the `custom_components` directory in Home Assistant.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services**, add **Glowrium**, and choose one or both setup options:
   - **Glowrium cloud account:** Sign in with your email address and password to enable remote control.
   - **Nearby Bluetooth light:** Select a discovered H1 or H4 and confirm that it is yours. No account or internet connection is required.

Bluetooth control requires a Home Assistant-supported adapter or an active ESPHome Bluetooth Proxy with an available connection slot. A passive scanner alone cannot control lights. The discovery process does not connect to or control a light until you confirm it.

## Supported Controls

| Model | Controls |
| --- | --- |
| H1 | Overall on/off, main light brightness, 2700–6500 K color temperature, scene presets, separate Main Light and Mood Light switches, Mood Light brightness, and Circadian Rhythm. |
| H4 | On/off, brightness, HS color, six color-temperature presets (2000, 2700, 4000, 5000, 6500, and 7500 K), dynamic and music effects, and effect speed. Brightness cannot be adjusted in music mode. |

## Connection Notes

- When the same light is added using both options, it appears as a single set of entities. Bluetooth is preferred. If Bluetooth fails before a command is sent, the linked cloud account can provide fallback control.
- A Bluetooth-only light does not have cloud fallback. Removing the cloud account does not remove a Bluetooth light that was added separately.
- Local Bluetooth access may not authenticate clients, so another nearby BLE client may also be able to control the light. Disconnect the manufacturer's app if it is using the light's Bluetooth connection.
- Setup only reads the light's status; it does not activate, link, reset, or update the device. If a factory-reset light needs activation, set it up first using the manufacturer's app.

## Troubleshooting

- If a Bluetooth light cannot be found, check the adapter or active proxy, available connection slots, signal range, and whether another app is already connected.
- If local control fails, download the Glowrium integration diagnostics to check the Bluetooth connection status and failure details.
- If cloud control prompts you to sign in again, use the account originally used for setup.
