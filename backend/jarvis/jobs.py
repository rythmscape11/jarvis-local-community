import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .store import uid, now
from .documents import index


class Jobs:
    def __init__(self, store):
        self.store = store
        self.queue = asyncio.Queue(maxsize=16)
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="jarvis-index"
        )
        self.stops = {}
        self.worker = None
        self.news = None
        self.workflows = None

    def start(self):
        self.worker = asyncio.create_task(self.loop())

    def submit(self, root=None, kind="index_documents"):
        if self.queue.full():
            raise ValueError("Background queue is full")
        id = uid()
        self.store.run(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
            (
                id,
                kind,
                json.dumps({"root": root}),
                "queued",
                None,
                None,
                now(),
                now(),
            ),
        )
        self.stops[id] = threading.Event()
        self.queue.put_nowait((id, kind, root))
        return id

    async def loop(self):
        while True:
            id, kind, root = await self.queue.get()
            stop = self.stops[id]
            try:
                if stop.is_set():
                    continue
                self.store.run(
                    "UPDATE jobs SET state='running',updated=? WHERE id=?", (now(), id)
                )
                deadline = time.monotonic() + 120
                if kind == "workflow_run":
                    if not self.workflows:
                        raise ValueError("Workflow engine unavailable")
                    result = await asyncio.wait_for(self.workflows.execute(root), 600)
                elif kind == "news_refresh":
                    if not self.news:
                        raise ValueError("News adapter unavailable")
                    result = await asyncio.wait_for(self.news.refresh(stop.is_set), 120)
                else:
                    result = await asyncio.get_running_loop().run_in_executor(
                        self.executor,
                        index,
                        self.store,
                        root,
                        lambda: stop.is_set() or time.monotonic() > deadline,
                    )
                state = "cancelled" if stop.is_set() else "succeeded"
                self.store.run(
                    "UPDATE jobs SET state=?,result=?,updated=? WHERE id=?",
                    (state, json.dumps(result), now(), id),
                )
            except InterruptedError:
                self.store.run(
                    "UPDATE jobs SET state=?,error=?,updated=? WHERE id=?",
                    (
                        "cancelled" if stop.is_set() else "failed",
                        "Cancelled or indexing deadline exceeded",
                        now(),
                        id,
                    ),
                )
            except asyncio.CancelledError:
                if stop.is_set() and self.worker and not self.worker.cancelling():
                    self.store.run(
                        "UPDATE jobs SET state='cancelled',updated=? WHERE id=?",
                        (now(), id),
                    )
                    continue
                stop.set()
                self.store.run(
                    "UPDATE jobs SET state='interrupted',updated=? WHERE id=? AND state='running'",
                    (now(), id),
                )
                raise
            except Exception as error:
                self.store.run(
                    "UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?",
                    (str(error)[:300], now(), id),
                )
            finally:
                self.queue.task_done()
                self.stops.pop(id, None)

    def cancel(self, id):
        if id in self.stops:
            self.stops[id].set()
            self.store.run(
                "UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state IN ('queued','running')",
                (now(), id),
            )

    async def close(self):
        for stop in self.stops.values():
            stop.set()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        self.executor.shutdown(wait=True, cancel_futures=True)
