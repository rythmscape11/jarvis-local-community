"""Process-local credential reads shared by model and speech adapters.

Only OS keyring persists credentials. Pending reads survive caller cancellation;
successful reads and denied reads are reused until explicit invalidation or exit.
"""

import asyncio


class Credentials:
    def __init__(self):
        self.reads = {}

    def invalidate(self, account):
        # A blocked OS thread cannot be cancelled safely. Detach it; consumers
        # must not use its result after credentials change.
        self.reads.pop(account, None)

    def retry(self, account):
        task = self.reads.get(account)
        if task is not None and task.done():
            self.invalidate(account)

    async def read(self, account, loader=None, timeout=8):
        if account not in self.reads:
            if loader is None:
                import keyring

                def loader():
                    return keyring.get_password("Jarvis Local", account)

            async def load():
                try:
                    return await asyncio.to_thread(loader) or ""
                except Exception as error:
                    raise ValueError(
                        "Keychain access wasn't approved. Use Test API connection to retry, or choose local Ollama and a local voice."
                    ) from error

            self.reads[account] = asyncio.create_task(load())
            self.reads[account].add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
        task = self.reads[account]
        try:
            value = await asyncio.wait_for(asyncio.shield(task), timeout)
        except TimeoutError as error:
            raise ValueError(
                "Approve the Jarvis runtime Keychain prompt using your Mac login password. Local Ollama and local voices need no API key."
            ) from error
        if self.reads.get(account) is not task:
            raise ValueError("Credentials changed during this request. Try again.")
        return value


credentials = Credentials()
