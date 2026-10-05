"""Navigation handoff: native Maps calculates directions, never invented by the LLM."""

from typing import Literal
from urllib.parse import urlencode
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .exports import create_document


class Directions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: str = Field(
        min_length=2,
        max_length=300,
        description="Actual destination supplied by the owner",
    )
    origin: str = Field(
        default="",
        max_length=300,
        description="Leave empty for native Maps current location; Jarvis does not collect GPS",
    )
    mode: Literal["driving", "walking", "transit", "cycling"] = "driving"

    @field_validator("destination", "origin")
    @classmethod
    def plain_address(cls, value):
        if any(ord(c) < 32 for c in value) or (value and not value.strip()):
            raise ValueError("Use a plain, nonempty address")
        return value


def directions(query):
    apple = {
        "daddr": query.destination,
        "dirflg": {"driving": "d", "walking": "w", "transit": "r", "cycling": "d"}[
            query.mode
        ],
    }
    google = {
        "api": "1",
        "destination": query.destination,
        "travelmode": {"cycling": "bicycling"}.get(query.mode, query.mode),
    }
    if query.origin:
        apple["saddr"] = query.origin
        google["origin"] = query.origin
    return {
        "apple_maps_url": ("https://maps.apple.com/?" + urlencode(apple))
        if query.mode != "cycling"
        else None,
        "google_maps_url": "https://www.google.com/maps/dir/?" + urlencode(google),
        "mode": query.mode,
        "destination": query.destination,
        "status": "navigation_links_ready",
        "route_verified": False,
        "live_navigation": "Native Maps on the phone provides current turn-by-turn instructions. Jarvis does not fabricate steps or ETA.",
        "apple_cycling_supported_by_link": query.mode != "cycling",
    }


class AppointmentBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recipient: str = Field(min_length=1, max_length=150)
    purpose: str = Field(min_length=1, max_length=1500)
    preferred_times: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Owner supplied preferred times, with timezone",
    )
    questions: list[str] = Field(default_factory=list, max_length=15)
    number: str = Field(default="", max_length=20, pattern=r"^(?:\+[1-9][0-9]{7,14})?$")


def brief(store, query):
    content = "\n".join(
        [
            "## Recipient",
            query.recipient,
            query.number or "Phone number not supplied.",
            "## Appointment purpose",
            query.purpose,
            "## Preferred times",
            *("- " + v for v in query.preferred_times),
            "## Questions to ask",
            *("- " + v for v in query.questions),
            "## Confirmation checklist",
            "- Confirm date, local timezone, address or meeting link.",
            "- Ask about preparation and cancellation rules.",
            "- Tell Jarvis the confirmed details to prepare a calendar entry.",
            "No call placed and no appointment booked. You conduct the call.",
        ]
    )
    return create_document(store, "Appointment call brief", content, "md") | {
        "appointment_booked": False,
        "call_placed": False,
    }
