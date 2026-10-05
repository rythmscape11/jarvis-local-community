"""Owner-reviewed primary calendar writes. No recurring series or arbitrary endpoints."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .store import uid, now

PATH = "calendar/v3/calendars/primary/events"


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(
        max_length=60, description="ISO 8601 datetime with timezone offset"
    )
    end: str = Field(
        max_length=60, description="ISO 8601 datetime with timezone offset"
    )
    timezone: str = Field(default="Asia/Kolkata", max_length=100)
    description: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid_times(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Choose a valid IANA timezone") from error
        first, last = (
            datetime.fromisoformat(self.start),
            datetime.fromisoformat(self.end),
        )
        if not self.title.strip() or first.tzinfo is None or last.tzinfo is None:
            raise ValueError("Provide a title and start/end with timezone offsets")
        if not timedelta(0) < last - first <= timedelta(days=7):
            raise ValueError("Event must end after it starts, within seven days")
        if any(d.utcoffset() != d.astimezone(zone).utcoffset() for d in (first, last)):
            raise ValueError("Datetime offsets must match the selected timezone")
        return self

    def payload(self):
        return {
            "summary": self.title,
            "start": {"dateTime": self.start, "timeZone": self.timezone},
            "end": {"dateTime": self.end, "timeZone": self.timezone},
            "description": self.description,
            "location": self.location,
        }


class CalendarUpdate(CalendarEvent):
    event_id: str = Field(
        pattern=r"^[a-zA-Z0-9_]{5,200}$",
        description="Actual ID from read_calendar; never infer it",
    )


async def prepare(connector, event):
    if not connector.config("calendar_write")["connected"]:
        raise ValueError(
            "Calendar editing: Not connected. Connect it in Workspace → Automations → Connections."
        )
    args = {"event": event.payload()}
    kind = "create_calendar_event"
    if isinstance(event, CalendarUpdate):
        kind = "update_calendar_event"
        old = await connector.request(
            "calendar_write", "GET", PATH + "/" + event.event_id
        )
        if (
            old.get("status") == "cancelled"
            or old.get("recurrence")
            or old.get("recurringEventId")
        ):
            raise ValueError("Only a single active non-recurring event can be edited")
        if not old.get("etag") or not old.get("organizer", {}).get("self"):
            raise ValueError("Only your own organized events can be edited")
        for field in ("description", "location"):
            if field not in event.model_fields_set:
                args["event"][field] = old.get(field, "")
        args.update(
            event_id=event.event_id,
            etag=old["etag"],
            before={
                k: old.get(k)
                for k in (
                    "summary",
                    "start",
                    "end",
                    "description",
                    "location",
                    "attendees",
                )
            },
        )
        args["notify_guests"] = bool(old.get("attendees"))
    else:
        # Google event IDs accept base32hex. A stable supplied ID also protects
        # against duplicates if the upstream response becomes uncertain.
        args.update(event_id=uid().replace("-", ""), notify_guests=False)
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
        (action_id, None, kind, json.dumps(args), "pending", None, now(), now()),
    )
    return {
        "action_id": action_id,
        "status": "awaiting_approval",
        "message": "Review exact calendar details in Automations → Connections before saving. No calendar change has run.",
        "notify_existing_guests": args["notify_guests"],
    }


async def perform(connector, kind, args):
    event = args["event"]
    path = PATH + "/" + args["event_id"]
    if kind == "create_calendar_event":
        response = await connector.request(
            "calendar_write",
            "POST",
            PATH,
            params={"sendUpdates": "none"},
            json={**event, "id": args["event_id"]},
        )
    else:
        response = await connector.request(
            "calendar_write",
            "PATCH",
            path,
            headers={"If-Match": args["etag"]},
            params={"sendUpdates": "all" if args["notify_guests"] else "none"},
            json=event,
        )
    if response.get("id") != args["event_id"]:
        raise InterruptedError(
            "Calendar write returned no matching event ID; inspect Google Calendar"
        )
    try:
        verified = await connector.request("calendar_write", "GET", path)
        if verified.get("id") != args["event_id"]:
            raise ValueError("Saved event ID differs")
        for field in ("summary", "description", "location"):
            if verified.get(field, "") != event[field]:
                raise ValueError("Saved fields differ")
        for field in ("start", "end"):
            if datetime.fromisoformat(
                verified[field]["dateTime"]
            ) != datetime.fromisoformat(event[field]["dateTime"]):
                raise ValueError("Saved time differs")
        if verified.get("status") == "cancelled":
            raise ValueError("Event is cancelled")
    except Exception as error:
        raise InterruptedError(
            "Calendar write could not be verified; inspect Google Calendar before retrying"
        ) from error
    return {
        "event_id": verified["id"],
        "title": verified["summary"],
        "start": verified["start"],
        "end": verified["end"],
        "status": "created" if kind == "create_calendar_event" else "updated",
        "verified": True,
        "guest_notifications_requested": args["notify_guests"],
    }
