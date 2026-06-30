# ElderCare AI — MCU sensor/actuator facade over the Bridge (the "IoT" pillar).
#
# Thin, well-typed wrapper around the Bridge.call(...) names the sketch
# registers with Bridge.provide(...). One source of truth for the cross-chip
# contract on the Python side — if the sketch renames a function, only this
# file changes.

from arduino.app_utils import Bridge

# Modulino Buttons indices (must match sketch isPressed order).
# A/B/C dispense medication channels 0/1/2 respectively.
BTN_A = 0
BTN_B = 1
BTN_C = 2


# --- actuators (Python -> MCU) ------------------------------------------
def set_led(on: bool):
    Bridge.call("set_led", bool(on))


def pixels_progress(count: int):
    """Light count/8 Modulino pixels (face-detection progress bar)."""
    Bridge.call("pixels_progress", int(count))


def buzzer_beep(freq: int = 1800, ms: int = 200):
    """One short tone — pill-dispense confirm / UI feedback."""
    Bridge.call("buzzer_beep", int(freq), int(ms))


def buzzer_alarm(on: bool):
    """Sustained emergency tone (SOS)."""
    Bridge.call("buzzer_alarm", bool(on))


def dispense_pill(channel: int = 0) -> bool:
    """Sweep one dispenser servo. channel 0 = A (pin 9), 1 = B (pin 10)."""
    try:
        return bool(Bridge.call("dispense_pill", int(channel)))
    except Exception as exc:
        print(f"[sensors] dispense_pill failed: {exc}")
        return False


# --- sensors (Python polls MCU) -----------------------------------------
def read_temperature() -> float:
    return float(Bridge.call("read_temperature"))


def read_humidity() -> float:
    return float(Bridge.call("read_humidity"))


def _button(idx: int) -> bool:
    """Latched press: true exactly once per physical press."""
    return bool(Bridge.call("get_and_clear_button", int(idx)))


def button_a() -> bool:
    return _button(BTN_A)


def button_b() -> bool:
    return _button(BTN_B)


def button_c() -> bool:
    return _button(BTN_C)
