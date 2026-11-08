"""Single-slot newest-only inference queue.

Audio capture never waits for inference, even if the model takes longer than
its nominal one-second hop. Under pressure, outdated *pending* windows are
replaced; audio is still continuously captured and monitored.
"""
import asyncio


class NewestWindowQueue:
    def __init__(self):
        self._queue = asyncio.Queue(maxsize=1)
        self.dropped = 0

    def qsize(self):
        return self._queue.qsize()

    def submit(self, item):
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(item)

    async def get(self):
        return await self._queue.get()

    def task_done(self):
        self._queue.task_done()

    def clear(self):
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                return
