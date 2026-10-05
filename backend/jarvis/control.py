"""Owner-confirmed system input. No action executes merely because a model asks."""

import asyncio
import io
import json
import sys
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from .config import APPS
from .store import uid, now


class SystemAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["click", "scroll", "hotkey", "type_text"]
    application: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=300)
    x: int = Field(default=0, ge=0, le=10000)
    y: int = Field(default=0, ge=0, le=10000)
    amount: int = Field(default=0, ge=-10, le=10)
    keys: list[str] = Field(default_factory=list, max_length=4)
    text: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def validate_action(self):
        allowed = {
            "command",
            "ctrl",
            "alt",
            "shift",
            "tab",
            "escape",
            "enter",
            "space",
            "up",
            "down",
            "left",
            "right",
            "a",
            "c",
            "v",
            "x",
            "z",
            "s",
            "f",
            "home",
            "end",
            "backspace",
            "delete",
        }
        if any(key not in allowed for key in self.keys):
            raise ValueError("Key is not allowed")
        if self.action == "hotkey" and not self.keys:
            raise ValueError("Specify keys")
        if self.action == "type_text" and (not self.text or not self.text.isascii()):
            raise ValueError(
                "System typing initially supports nonempty ASCII text only"
            )
        if self.application not in APPS:
            raise ValueError("Target application must be configured in the allowlist")
        return self


class Control:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self.lock = asyncio.Lock()
        self.store.run(
            "UPDATE control_requests SET state='expired' WHERE state IN ('pending','running')"
        )

    def propose(self, args: SystemAction):
        if not self.settings().computer_control:
            raise ValueError(
                "System control is off. The owner must enable it in Settings."
            )
        id = uid()
        self.store.run(
            "INSERT INTO control_requests VALUES(?,?,?,?,?,?)",
            (id, json.dumps(args.model_dump()), "pending", None, now(), None),
        )
        return {
            "request_id": id,
            "state": "awaiting_owner_approval",
            "action": args.model_dump(),
            "message": "No input delivered. Review target and action, then explicitly approve in the dashboard.",
        }

    async def approve(self, id, approved):
        async with self.lock:
            rows = self.store.all("SELECT * FROM control_requests WHERE id=?", (id,))
            if not rows:
                raise ValueError("Action request not found")
            row = rows[0]
            if row["state"] != "pending":
                raise ValueError("Action is no longer pending; it will not be replayed")
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(row["created"])
            ).total_seconds()
            if age > 300:
                self.store.run(
                    "UPDATE control_requests SET state='expired' WHERE id=?", (id,)
                )
                raise ValueError("Action expired after five minutes")
            if not approved:
                self.store.run(
                    "UPDATE control_requests SET state='rejected',updated=? WHERE id=?",
                    (now(), id),
                )
                return {"ok": True, "state": "rejected"}
            if not self.settings().computer_control:
                raise ValueError("System control is disabled")
            args = SystemAction.model_validate_json(row["args"])
            self.store.run(
                "UPDATE control_requests SET state='running',updated=? WHERE id=?",
                (now(), id),
            )
            try:
                await asyncio.sleep(3)
                result = await asyncio.wait_for(
                    asyncio.to_thread(self.execute, args), 8
                )
                state = "succeeded"
            except asyncio.TimeoutError:
                result = {
                    "ok": False,
                    "error": "OS input timed out; an action may already have taken effect. Inspect the target before requesting another action.",
                }
                state = "interrupted"
            except Exception as error:
                result = {"ok": False, "error": str(error)[:300]}
                state = "failed"
            self.store.run(
                "UPDATE control_requests SET state=?,result=?,updated=? WHERE id=?",
                (state, json.dumps(result), now(), id),
            )
            return result

    def foreground(self):
        if sys.platform == "darwin":
            import subprocess

            process = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    'tell application "System Events" to get bundle identifier of first application process whose frontmost is true',
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if process.returncode:
                raise ValueError(
                    "macOS Automation permission is required to verify the foreground application"
                )
            return process.stdout.strip()
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid)
            )
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x1000, False, pid.value)
            if not handle:
                raise ValueError("Unable to verify foreground process")
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if not kernel.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)
                ):
                    raise ValueError("Unable to resolve foreground executable")
                return buffer.value
            finally:
                kernel.CloseHandle(handle)
        raise ValueError("System control supports macOS and Windows")

    def execute(self, args):
        import pyautogui

        if sys.platform == "darwin":
            import Quartz

            if not Quartz.AXIsProcessTrusted():
                raise ValueError(
                    "Grant Accessibility to Jarvis Local in macOS System Settings → Privacy & Security → Accessibility"
                )
        target = APPS[args.application]
        # Owner brings target to foreground. Never type into an unexpected application.
        foreground = self.foreground()
        if foreground.lower() != target.lower():
            raise ValueError(
                "Foreground target changed. Bring "
                + args.application
                + " to front and request a fresh action."
            )
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.15
        width, height = pyautogui.size()
        if args.action == "click":
            if args.x >= width or args.y >= height:
                raise ValueError("Coordinates are outside the screen")
            pyautogui.click(args.x, args.y)
        elif args.action == "scroll":
            pyautogui.scroll(args.amount)
        elif args.action == "hotkey":
            pyautogui.hotkey(*args.keys)
        elif args.action == "type_text":
            pyautogui.write(args.text, interval=0.005)
        return {
            "ok": True,
            "state": "input_delivered",
            "application": args.application,
            "action": args.action,
            "verified": "OS input function returned. The resulting application task is not semantically verified.",
        }

    def snapshot(self):
        if not self.settings().computer_control:
            raise ValueError("Enable system control first")
        import pyautogui

        image = pyautogui.screenshot()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
