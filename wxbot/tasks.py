"""Background tasks that are not lost halfway.

The event loop only keeps a weak reference to a task, so a fire-and-forget task that nobody else
holds can be garbage collected before it finishes (see the note under asyncio.create_task in the
Python docs). Everything the bot starts in the background goes through spawn(), which holds the
task until it is done.
"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_running: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    task = asyncio.ensure_future(coro)
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task
