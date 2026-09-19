"""asyncio helpers."""

import asyncio
from typing import Awaitable, Iterable


async def run_all(coroutines: Iterable[Awaitable]) -> None:
    """
    Runs coroutines concurrently until all finish. Unlike asyncio.gather, the
    first exception (or a cancellation of the caller) cancels every sibling
    before propagating — no orphaned streams keep running in the background
    when the caller reconnects and starts a fresh set.
    """
    tasks = [asyncio.ensure_future(c) for c in coroutines]
    if not tasks:
        return
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()   # re-raises the first failure, if any
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
