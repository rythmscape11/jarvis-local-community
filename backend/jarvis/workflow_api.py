"""Authenticated local routes; only OAuth's state-checked callback is public."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from .workflows import WorkflowDefinition
from .custom_api import APIConfig, read_api
from .connectors import Action, HomeConfig, MailReply


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Start(Strict):
    key: str = Field(min_length=16, max_length=100)


class Review(Strict):
    approve: bool


class PhoneSetting(Strict):
    enabled: bool


def routes(workflows, connectors):
    api = APIRouter()

    @api.get("/api/automations")
    async def snapshot():
        return {**workflows.snapshot(), "connectors": connectors.snapshot()}

    @api.put("/api/connectors/iphone")
    async def iphone(body: PhoneSetting):
        from .phone import available

        if body.enabled and not available():
            raise HTTPException(400, "A Mac with the native Phone app is required")
        connectors.store.run(
            "INSERT OR REPLACE INTO connectors VALUES(?,?,?)",
            ("iphone", "{}", int(body.enabled)),
        )
        if not body.enabled:
            connectors.store.run(
                "UPDATE external_actions SET state='rejected' WHERE state='pending' AND kind='iphone_call'"
            )
        return {"enabled": body.enabled, "call_audio_agent": False}

    @api.get("/api/automation-notifications")
    async def unread_notifications():
        return workflows.store.all(
            "SELECT id,title FROM workflow_notifications WHERE read=0 ORDER BY created DESC LIMIT 60"
        )

    @api.post("/api/automations")
    async def create(body: WorkflowDefinition):
        if len(workflows.store.all("SELECT id FROM workflows")) >= 100:
            raise HTTPException(400, "At most 100 workflows")
        return workflows.save(body)

    @api.put("/api/automations/{id}")
    async def update(id: str, body: WorkflowDefinition):
        if not workflows.store.all("SELECT id FROM workflows WHERE id=?", (id,)):
            raise HTTPException(404, "Workflow not found")
        return workflows.save(body, id)

    @api.delete("/api/automations/{id}")
    async def delete(id: str):
        for row in workflows.store.all(
            "SELECT id FROM workflow_runs WHERE workflow_id=? AND state IN ('queued','running','awaiting_approval')",
            (id,),
        ):
            workflows.cancel(row["id"])
        with workflows.store.lock:
            ids = [
                r["id"]
                for r in workflows.store.all(
                    "SELECT id FROM workflow_runs WHERE workflow_id=?", (id,)
                )
            ]
            for run_id in ids:
                for table in (
                    "workflow_steps",
                    "workflow_notifications",
                    "external_actions",
                ):
                    workflows.store.run(
                        f"DELETE FROM {table} WHERE run_id=?", (run_id,)
                    )
            workflows.store.run("DELETE FROM workflow_runs WHERE workflow_id=?", (id,))
            workflows.store.run("DELETE FROM workflows WHERE id=?", (id,))
        return {"deleted": True, "files_retained": True}

    @api.post("/api/automations/{id}/run")
    async def run(id: str, body: Start):
        try:
            return workflows.start(id, body.key)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @api.post("/api/automation-runs/{id}/cancel")
    async def cancel(id: str):
        try:
            return workflows.cancel(id)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @api.post("/api/automation-notifications/{id}/read")
    async def mark_read(id: str):
        workflows.store.run(
            "UPDATE workflow_notifications SET read=1 WHERE id=?", (id,)
        )
        return {"read": True}

    @api.post("/api/connectors/{profile}/connect")
    async def connect(profile: str):
        try:
            return {"url": connectors.begin(profile)}
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)[:200])

    @api.get("/api/connectors/google/callback")
    async def callback(state: str = "", code: str = ""):
        try:
            await connectors.finish(state, code)
        except Exception:
            return HTMLResponse(
                "Google connection failed. Check Desktop OAuth configuration, enabled API and test users. Return to Jarvis to retry.",
                status_code=400,
            )
        return HTMLResponse(
            "Google connector connected. Return to Jarvis Local. You may close this tab."
        )

    @api.delete("/api/connectors/{profile}")
    async def disconnect(profile: str):
        try:
            await connectors.disconnect(profile)
            return {"connected": False}
        except ValueError as error:
            raise HTTPException(400, str(error))

    @api.post("/api/connectors/home/configure")
    async def home(body: HomeConfig):
        try:
            return await connectors.configure_home(body)
        except Exception:
            raise HTTPException(
                400,
                "Could not store Home Assistant connection in OS credential storage",
            )

    @api.get("/api/connectors/{profile}/read")
    async def read(profile: str):
        try:
            return await connectors.read(profile)
        except Exception as error:
            raise HTTPException(400, str(error)[:200])

    @api.post("/api/custom-apis")
    async def configure_api(body: APIConfig):
        try:
            return await connectors.configure_api(body)
        except Exception:
            raise HTTPException(
                400,
                "Could not configure API; check public HTTPS endpoint and OS credential access",
            )

    @api.get("/api/custom-apis/{name}")
    async def custom_read(name: str):
        try:
            return await read_api(connectors, name)
        except Exception as error:
            raise HTTPException(400, str(error)[:200])

    @api.get("/api/email/{message_id}")
    async def email(message_id: str):
        try:
            return await connectors.read_message(message_id)
        except Exception as error:
            raise HTTPException(400, str(error)[:200])

    @api.post("/api/email/reply")
    async def reply(body: MailReply):
        try:
            return await connectors.prepare_reply(body.message_id, body.content)
        except Exception as error:
            raise HTTPException(400, str(error)[:200])

    @api.post("/api/external-actions")
    async def propose(body: Action):
        try:
            return connectors.propose(body.kind, body.model_dump(exclude={"kind"}))
        except ValueError as error:
            raise HTTPException(400, str(error))

    @api.post("/api/external-actions/{id}/review")
    async def review(id: str, body: Review):
        try:
            return await connectors.review(id, body.approve)
        except ValueError as error:
            raise HTTPException(400, str(error))
        except Exception:
            raise HTTPException(
                503,
                "Action interrupted. Inspect its activity record and account/device before retrying.",
            )

    return api
