import asyncio
import sys
from pathlib import Path
from .config import APPS


async def open_application(name):
    if name not in APPS:
        raise ValueError("Application not allowlisted. Available: " + ", ".join(APPS))
    identifier = APPS[name]
    if sys.platform == "darwin":
        command = ["/usr/bin/open", "-b", identifier]
    elif sys.platform == "win32":
        path = Path(identifier).resolve(strict=True)
        if path.suffix.lower() != ".exe" or not path.is_file():
            raise ValueError(
                "Windows apps require an explicitly configured absolute .exe path"
            )
        command = [str(path)]
    else:
        raise ValueError("Application launcher supports macOS and Windows only")
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        if sys.platform == "win32":
            return {
                "name": name,
                "state": "launch_requested",
                "pid": process.pid,
                "verified": "Process created; window visibility is not verified",
            }
        _, err = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        raise
    if process.returncode:
        raise ValueError(err.decode()[:200] or "Operating system rejected launch")
    return {
        "name": name,
        "identifier": identifier,
        "state": "launch_requested",
        "verified": "macOS accepted request; window visibility is not verified",
    }
