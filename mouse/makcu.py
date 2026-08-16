import time
import threading
from makcu import create_controller, MouseButton


BUTTONS = {
    "LMB": MouseButton.LEFT,
    "RMB": MouseButton.RIGHT,
    "MMB": MouseButton.MIDDLE,
    "M4": MouseButton.MOUSE4,
    "M5": MouseButton.MOUSE5,
}

POLL_MAP = {
    "left": "LMB",
    "right": "RMB",
    "middle": "MMB",
    "mouse4": "M4",
    "mouse5": "M5",
}


class makcu_controller:
    controller = None

    button_states = {
        "LMB": False,
        "RMB": False,
        "MMB": False,
        "M4": False,
        "M5": False,
    }

    connection_lock = threading.Lock()
    button_lock = threading.Lock()
    is_connected_flag = False
    last_error: str | None = None
    move_count = 0

    @staticmethod
    def is_connected():
        with makcu_controller.connection_lock:
            return (
                makcu_controller.is_connected_flag
                and makcu_controller.controller is not None
            )

    @staticmethod
    def _apply_polled_states(states: dict) -> None:
        with makcu_controller.button_lock:
            for poll_name, our_name in POLL_MAP.items():
                if poll_name in states:
                    makcu_controller.button_states[our_name] = bool(states[poll_name])

    @staticmethod
    def refresh_button_states() -> None:
        if not makcu_controller.is_connected():
            return
        try:
            states = makcu_controller.controller.get_button_states()
            if isinstance(states, dict):
                makcu_controller._apply_polled_states(states)
        except Exception as e:
            print(f"[MAKCU] Button poll error: {e}")

    @staticmethod
    def _ensure_unlocked() -> None:
        mck = makcu_controller.controller
        if mck is None:
            return
        try:
            mck.lock_mouse_x(False)
            mck.lock_mouse_y(False)
        except Exception:
            try:
                mck.unlock("X")
                mck.unlock("Y")
            except Exception:
                pass

    @staticmethod
    def connect():
        with makcu_controller.connection_lock:
            if not makcu_controller.is_connected_flag and makcu_controller.controller is not None:
                try:
                    makcu_controller.controller.disconnect()
                except Exception:
                    pass
                makcu_controller.controller = None

            if makcu_controller.controller is None:
                try:
                    makcu_controller.controller = create_controller(
                        debug=False,
                        auto_reconnect=True,
                    )

                    def on_button_event(button: MouseButton, pressed: bool):
                        with makcu_controller.button_lock:
                            for name, btn in BUTTONS.items():
                                if btn == button:
                                    makcu_controller.button_states[name] = pressed
                                    break

                    makcu_controller.controller.set_button_callback(on_button_event)
                    makcu_controller.controller.enable_button_monitoring(True)
                    makcu_controller._ensure_unlocked()
                    makcu_controller.refresh_button_states()

                    makcu_controller.is_connected_flag = True
                    makcu_controller.last_error = None
                    makcu_controller._logged_connect_fail = False
                    print("[MAKCU] Connected.")

                except Exception as e:
                    makcu_controller.last_error = str(e)
                    if not getattr(makcu_controller, "_logged_connect_fail", False):
                        print(f"[MAKCU] Connection error: {e}")
                        makcu_controller._logged_connect_fail = True
                    makcu_controller.is_connected_flag = False
                    makcu_controller.controller = None
                    return None

            return makcu_controller.controller

    @staticmethod
    def StartButtonListener():
        makcu_controller.connect()

    @staticmethod
    def simple_move_mouse(x, y):
        if not makcu_controller.is_connected():
            return False
        if x == 0 and y == 0:
            return True

        try:
            makcu_controller.controller.move(int(x), int(y))
            makcu_controller.move_count += 1
            return True
        except Exception as e:
            print(f"[MAKCU] Move error: {e}")
            makcu_controller.last_error = str(e)
            makcu_controller.is_connected_flag = False
            return False

    @staticmethod
    def get_interlock_held(primary: str, secondary: str) -> bool:
        return (
            makcu_controller.get_button_state(primary)
            and makcu_controller.get_button_state(secondary)
        )

    @staticmethod
    def get_button_state(button_name: str):
        makcu_controller.refresh_button_states()
        with makcu_controller.button_lock:
            return makcu_controller.button_states.get(button_name, False)

    @staticmethod
    def get_debug() -> dict:
        with makcu_controller.button_lock:
            buttons = dict(makcu_controller.button_states)
        return {
            "connected": makcu_controller.is_connected(),
            "last_error": makcu_controller.last_error,
            "move_count": makcu_controller.move_count,
            "buttons": buttons,
        }

    @staticmethod
    def disconnect():
        with makcu_controller.connection_lock:
            if makcu_controller.controller:
                try:
                    makcu_controller.controller.disconnect()
                except Exception:
                    pass

            makcu_controller.controller = None
            makcu_controller.is_connected_flag = False
