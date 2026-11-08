"""Run: python -m unittest discover -s tests -p test_continuous.py -v

These tests exercise queue and HTTP state transitions without needing
PellaV2 checkpoint or a LiveKit server.
"""
import asyncio
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice_detector'))
from continuous_queue import NewestWindowQueue


class TestNewestWindowQueue(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_and_latest_wins(self):
        queue = NewestWindowQueue()
        for n in range(30):
            queue.submit(n)
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.dropped, 29)
        self.assertEqual(await queue.get(), 29)
        queue.task_done()
        self.assertEqual(queue.qsize(), 0)

    async def test_audio_producer_is_independent_of_slow_model(self):
        queue = NewestWindowQueue()
        inference_started = asyncio.Event()
        inference_can_finish = asyncio.Event()
        processed = []

        async def model_worker():
            first = await queue.get()
            inference_started.set()
            await inference_can_finish.wait()  # The model is "busy".
            processed.append(first)
            queue.task_done()
            processed.append(await queue.get())
            queue.task_done()

        queue.submit(0)
        task = asyncio.create_task(model_worker())
        await inference_started.wait()
        # This simulates 20 new audio windows arriving WHILE model is busy.
        for i in range(1, 21):
            queue.submit(i)
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.dropped, 19)
        inference_can_finish.set()
        await task
        self.assertEqual(processed, [0, 20])
        self.assertEqual(queue.qsize(), 0)

    async def test_clear_on_new_caller(self):
        queue = NewestWindowQueue()
        queue.submit(('old-call', 1))
        queue.clear()
        self.assertEqual(queue.qsize(), 0)
        queue.submit(('new-call', 1))
        self.assertEqual(await queue.get(), ('new-call', 1))
        queue.task_done()


class TestDetectionHTTPState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('voiceshield_server_for_test', ROOT / 'server.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.module.WORKER_TOKEN = 'unit-test-token'
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.module.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def send(self, data):
        req = Request(self.base + '/api/internal/detection',
                      data=json.dumps(data).encode(), method='POST',
                      headers={'Content-Type':'application/json','X-Worker-Token':'unit-test-token'})
        with urlopen(req) as r:
            self.assertEqual(r.status, 200)

    def state(self):
        with urlopen(self.base + '/api/detection') as r:
            return json.load(r)

    def test_result_remains_visible_during_next_inference(self):
        self.send({'status':'result','verdict':'FAKE','p_fake':0.9,
                   'alert':True,'sample_age_ms':1000,'model_ms':980})
        d = self.state()
        self.assertEqual(d['p_fake'], 0.9)
        self.assertTrue(d['alert'])
        self.send({'status':'analyzing','message':'Analyzing newer audio'})
        d = self.state()
        self.assertEqual(d['status'], 'analyzing')
        self.assertEqual(d['p_fake'], 0.9)
        self.assertTrue(d['alert'])
        self.assertIsNotNone(d['last_result_at'])
        self.send({'status':'monitoring','message':'New call'})
        d = self.state()
        self.assertIsNone(d['p_fake'])
        self.assertFalse(d['alert'])


if __name__ == '__main__':
    unittest.main()
