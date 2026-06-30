# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An **Arduino App Lab** application targeting the **Arduino UNO Q**. The board is
dual-brain, and the app is split to match the hardware:

- **`python/`** — runs on the Qualcomm Linux microprocessor (MPU). Entry point is `python/main.py`.
- **`sketch/`** — a C++ Arduino sketch (`sketch.ino`) that runs on the STM32 microcontroller (MCU).
- **`app.yaml`** — the App Lab manifest. Declares the app name/description and any **Bricks**
  (managed services, mostly Docker containers on the Linux side) under `bricks:`.

This is not a normal Python or C++ project — it is built and deployed as a single App Lab app
that orchestrates both halves together.

## Commands

Run from the project root on the UNO Q (the `arduino-app-cli` is only present on the board):

```bash
arduino-app-cli app start .   # build sketch + start Python, deploy and run both halves
arduino-app-cli app logs  .   # stream logs
arduino-app-cli app stop  .   # stop the running app
```

There is no host-side build/test/lint setup; development happens against the board.

## Architecture: the two halves and the Bridge

The Python (MPU) and sketch (MCU) sides are separate processes/chips that communicate over the
**Bridge** RPC. This boundary is the core thing to understand before editing either side:

- **Sketch side** (`sketch/sketch.ino`): `#include <Arduino_RouterBridge.h>`, then in `setup()`
  call `Bridge.begin()` and register handlers with `Bridge.provide("name", fn)`. The function
  signature (param types, e.g. `bool`, `String`) defines the RPC contract.
- **Python side** (`python/main.py`): `from arduino.app_utils import *` exposes `Bridge` and `App`.
  Invoke a sketch-provided function with `Bridge.call("name", args...)`. End the entry point with
  `App.run()`, which manages the app lifecycle (long-running loops should run in their own thread
  or via a Brick callback so they don't block `App.run()`).

When you change a `Bridge.provide(...)` name or its parameter types in the sketch, the matching
`Bridge.call(...)` in Python must be updated in lockstep — there is no shared type checker across
the boundary.

## Bricks

Bricks are pre-built capabilities added under `bricks:` in `app.yaml` (e.g. `arduino:web_ui`) and
consumed in Python from `arduino.app_bricks.<brick>` (e.g. `from arduino.app_bricks.web_ui import WebUI`).
A WebUI brick exposes `ui.on_message(event, handler)`, `ui.send_message(event, payload)`, and
`ui.expose_api(method, path, handler)`. Add a brick to `app.yaml` first, then import and use it.

## Build profile

`sketch/sketch.yaml` pins the sketch to the `arduino:zephyr` platform — the UNO Q MCU runs under
Zephyr, not bare-metal AVR. Keep this profile unless intentionally retargeting.

## Conventions observed in Arduino's own examples

- Apply hardware quirks (e.g. active-low pins) on the Python side before the `Bridge.call`, and keep
  the sketch handler a thin `digitalWrite`/IO shim.
- Source files carry an SPDX license header in Arduino's examples; match the repo's own headers when present.
