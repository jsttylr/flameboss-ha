# Flame Boss / EGG Genius for Home Assistant (local)

A Home Assistant integration for Flame Boss and EGG Genius BBQ controllers that
talks to the controller directly over your home network. No cloud account, no
internet needed.

## What you get

- Pit temperature and up to three meat probes (blank when a probe is unplugged),
  with the probe labels and meat-done temperatures from the controller
- Blower output (%)
- Target pit temperature you can change from Home Assistant
- Alarm status (on while the controller is beeping) and a Silence alarm button
- Controller status (idle / running), cook timer end time
- Connected status, device ID, Wi-Fi signal and supply voltage (the last two are
  hidden by default)
- A `flameboss_alert` event for automations, fired when meat is done, the pit
  goes out of range, the pit alarm arms, or the controller suggests closing vents.
  The event data has a `type` such as `meat_alarm_triggered` and, for meat
  alarms, the probe number in `sensor`.

Temperatures follow your Home Assistant unit setting (Fahrenheit or Celsius).

## Good to know

Home Assistant talks to the MQTT broker built into the controller, using the
username `fb` and the controller's PIN, as described in Flame Boss's own API
documentation. Nothing goes through the internet. Find the PIN in the Flame Boss
or EGG Genius app under Controllers > Security > Show PIN.

The controller only accepts a few local connections at once, so close other
MQTT tools while Home Assistant is connected. Flame Boss notes the phone app
may show fewer live updates while a local client is connected.

## Install

With HACS: HACS > Integrations > three dots > Custom repositories, add this
repository's URL as an Integration, then install "Flame Boss / EGG Genius (local)"
and restart Home Assistant.

By hand: copy `custom_components/flameboss` into your Home Assistant
`config/custom_components/` folder and restart.

## Set up

Home Assistant may find the controller by itself (Settings > Devices &
services > Discovered). If it doesn't, click Add integration, search for
Flame Boss, and type the controller's IP address and PIN. Give the controller a fixed
IP address in your router so it doesn't move.

## Credits

Protocol details come from Flame Boss's
[API documentation](https://github.com/flameboss/fb-api-doc) and the
MIT-licensed [OpenBoss](https://github.com/sampscl/open_boss) project. This project is not affiliated with Flame Boss or Big Green Egg.
