"""Conflict-aware suggestions from the owner's actual primary calendar."""

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .calendar_actions import PATH


class Availability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: str = Field(max_length=60, description="ISO datetime with offset")
    end: str = Field(
        max_length=60,
        description="ISO datetime with offset; at most seven days after start",
    )
    timezone: str = Field(default="Asia/Kolkata", max_length=100)
    duration_minutes: int = Field(default=30, ge=15, le=240)
    day_start: int = Field(default=9, ge=0, le=23)
    day_end: int = Field(default=18, ge=1, le=24)

    @model_validator(mode="after")
    def validate_window(self):
        zone = ZoneInfo(self.timezone)
        first, last = (
            datetime.fromisoformat(self.start),
            datetime.fromisoformat(self.end),
        )
        if (
            first.tzinfo is None
            or last.tzinfo is None
            or not timedelta(0) < last - first <= timedelta(days=7)
        ):
            raise ValueError("Use aware datetimes within a seven day window")
        if self.day_end <= self.day_start:
            raise ValueError("Working hours must end after they start")
        if any(d.utcoffset() != d.astimezone(zone).utcoffset() for d in (first, last)):
            raise ValueError("Offsets must match the selected timezone")
        return self


async def suggest(connector, query):
    if not connector.config("calendar_write")["connected"]:
        raise ValueError(
            "Calendar editing: Not connected; availability needs the connected primary calendar"
        )
    events, page = [], None
    for _ in range(4):
        params = dict(
            timeMin=query.start,
            timeMax=query.end,
            singleEvents="true",
            orderBy="startTime",
            maxResults=100,
        )
        if page:
            params["pageToken"] = page
        result = await connector.request("calendar_write", "GET", PATH, params=params)
        events.extend(result.get("items", []))
        page = result.get("nextPageToken")
        if not page:
            break
    if page:
        raise ValueError(
            "Calendar window exceeds 400 events; choose a smaller window. No free slots assumed."
        )
    zone = ZoneInfo(query.timezone)
    first, last = datetime.fromisoformat(query.start), datetime.fromisoformat(query.end)
    busy = []
    for event in events:
        if (
            event.get("status") == "cancelled"
            or event.get("transparency") == "transparent"
        ):
            continue
        if any(
            a.get("self") and a.get("responseStatus") == "declined"
            for a in event.get("attendees", [])
        ):
            continue

        def stamp(part):
            if part.get("dateTime"):
                value = datetime.fromisoformat(part["dateTime"])
                if value.tzinfo is None:
                    raise ValueError("Calendar returned an ambiguous event time")
                return value
            return datetime.combine(
                datetime.fromisoformat(part["date"]).date(), time(), zone
            )

        busy.append((stamp(event["start"]), stamp(event["end"])))
    duration = timedelta(minutes=query.duration_minutes)
    cursor = first.astimezone(zone)
    # Round up to a 15-minute boundary, including seconds.
    cursor = cursor.replace(second=0, microsecond=0)
    if cursor < first or cursor.minute % 15:
        cursor += timedelta(minutes=15 - cursor.minute % 15)
    slots = []
    while cursor + duration <= last and len(slots) < 12:
        end = cursor + duration
        minutes = cursor.hour * 60 + cursor.minute
        end_minutes = (
            (end.date() - cursor.date()).days * 1440 + end.hour * 60 + end.minute
        )
        if (
            query.day_start * 60 <= minutes
            and end_minutes <= query.day_end * 60
            and not any(cursor < b and end > a for a, b in busy)
        ):
            slots.append(
                {
                    "start": cursor.isoformat(),
                    "end": end.isoformat(),
                    "timezone": query.timezone,
                }
            )
            cursor = end
        else:
            cursor += timedelta(minutes=15)
    return {
        "slots": slots,
        "checked_events": len(events),
        "source": "primary Google Calendar",
        "other_attendees_checked": False,
        "status": "suggested",
        "message": "Suggestions reflect only your calendar at check time. Recheck before approval; guests must confirm their availability.",
    }
