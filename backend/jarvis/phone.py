"""Explicitly reviewed macOS Phone handoff through the owner's linked iPhone."""

import asyncio
import sys
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .store import uid, now

PHONE_APP = Path("/System/Applications/Phone.app")


class PhoneCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    number: str = Field(
        pattern=r"^\+[1-9][0-9]{7,14}$",
        description="Actual owner-supplied international number; never guess",
    )
    purpose: str = Field(min_length=1, max_length=500)
    recipient: str = Field(min_length=1, max_length=150)


def available():
    return sys.platform == "darwin" and PHONE_APP.is_dir()


def prepare(connector, call):
    if not connector.config("iphone")["connected"] or not available():
        raise ValueError(
            "Enable iPhone calling in Automations → Connections on a Mac with the Phone app"
        )
    if (
        len(
            connector.store.all("SELECT id FROM external_actions WHERE state='pending'")
        )
        >= 100
    ):
        raise ValueError("At most 100 pending actions")
    action_id = uid()
    connector.store.run(
        "INSERT INTO external_actions VALUES(?,?,?,?,?,?,?,?)",
        (
            action_id,
            None,
            "iphone_call",
            call.model_dump_json(),
            "pending",
            None,
            now(),
            now(),
        ),
    )
    return {
        "action_id": action_id,
        "status": "awaiting_approval",
        "message": "Review recipient and number in Automations → Connections. Approval opens the Phone app; it does not verify connection or book an appointment. You conduct the conversation.",
    }


async def perform(connector, args):
    call = PhoneCall.model_validate(args)
    if not connector.config("iphone")["connected"] or not available():
        raise ValueError("iPhone calling is disabled or the Phone app is unavailable")
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/open",
        "-a",
        str(PHONE_APP),
        "tel:" + call.number,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await process.wait():
        raise ValueError(
            "macOS rejected the Phone handoff. Check Calls on Other Devices on your iPhone"
        )
    return {
        "status": "phone_handoff_requested",
        "recipient": call.recipient,
        "number": call.number,
        "call_connected_verified": False,
        "appointment_booked": False,
        "message": "Complete the call in the Phone app. Jarvis cannot speak or listen through the cellular call audio.",
    }
