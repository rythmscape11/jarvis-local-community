"""Synthetic reviewed dialing. Never places a physical call."""

import pytest
from jarvis.phone import PhoneCall, prepare, perform
from jarvis import phone
from jarvis.connectors import Connectors
from jarvis.store import Store


@pytest.mark.parametrize(
    "number",
    [
        "112",
        "+91112",
        "+1; rm -rf /",
        "tel:+14155550100",
        "+14155550100?x=1",
        "+00000000000",
    ],
)
def test_phone_number_boundary(number):
    with pytest.raises(ValueError):
        PhoneCall(number=number, purpose="Fixture", recipient="Synthetic recipient")


@pytest.mark.asyncio
async def test_dialing_is_reviewed_and_never_claims_a_booking(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite")
    connector = Connectors(store)
    store.run("INSERT INTO connectors VALUES(?,?,1)", ("iphone", "{}"))
    monkeypatch.setattr(phone, "available", lambda: True)
    commands = []

    class Process:
        async def wait(self):
            return 0

    async def launch(*args, **kwargs):
        commands.append(args)
        return Process()

    monkeypatch.setattr(phone.asyncio, "create_subprocess_exec", launch)
    p = prepare(
        connector,
        PhoneCall(
            number="+14155550100",
            recipient="Synthetic recipient",
            purpose="Ask about an appointment",
        ),
    )
    assert not commands
    result = await connector.review(p["action_id"], True)
    assert result["state"] == "succeeded"
    assert result["result"]["status"] == "phone_handoff_requested"
    assert result["result"]["call_connected_verified"] is False
    assert result["result"]["appointment_booked"] is False
    assert commands == [
        ("/usr/bin/open", "-a", str(phone.PHONE_APP), "tel:+14155550100")
    ]
    with pytest.raises(ValueError):
        await connector.review(p["action_id"], True)
    assert len(commands) == 1
    store.run("UPDATE connectors SET connected=0 WHERE id='iphone'")
    with pytest.raises(ValueError):
        await perform(
            connector,
            PhoneCall(
                number="+14155550100",
                recipient="Synthetic recipient",
                purpose="Fixture",
            ).model_dump(),
        )
    store.close()
