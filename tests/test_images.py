"""B6: every image reaches the API as a 256 x 256 data URL (offline)."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402


def decode(data_url):
    header, payload = data_url.split(',', 1)
    return header, Image.open(io.BytesIO(base64.b64decode(payload)))


class TestImages(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # an ASA24-like image (transparent background, 307 x 230) and a Nutrition5k-like one
        self.asa24 = os.path.join(self.tmp.name, 'asa24.png')
        image = Image.new('RGBA', (307, 230), (255, 255, 255, 0))
        image.paste((200, 120, 40, 255), (100, 60, 200, 170))
        image.save(self.asa24)
        self.nutrition5k = os.path.join(self.tmp.name, 'rgb.png')
        Image.new('RGB', (640, 480), (30, 90, 160)).save(self.nutrition5k)

    def test_resized_to_256(self):
        for path, mode in ((self.asa24, 'RGBA'), (self.nutrition5k, 'RGB')):
            header, image = decode(chagApp_openai.image_url(path))
            self.assertEqual(header, 'data:image/png;base64')
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.mode, mode)  # the transparent background is kept
        self.assertEqual(decode(chagApp_openai.image_url(self.asa24))[1].getpixel((0, 0)), (255, 255, 255, 0))

    def test_urls_pass_through(self):
        for url in ('data:image/png;base64,iVBORw0KGgo=', 'https://img.invalid/0.png'):
            self.assertEqual(chagApp_openai.image_url(url), url)

    def test_vision_chat_sends_the_resized_image(self):
        sent = []

        def fake_openai(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={
                'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '1 cup'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})
        env_path = os.path.join(self.tmp.name, '.env')
        with open(env_path, 'w') as f:
            f.write('OPENAI_API_KEY=sk-test\n')
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(fake_openai))
        with mock.patch.object(config, 'ENV_PATH', env_path), \
                mock.patch.object(config, 'API_LOG_PATH', os.path.join(self.tmp.name, 'log.jsonl')), \
                mock.patch.object(chagApp_openai, 'openai_client', client):
            chagApp_openai.Vision(config.MODELS['llm_vision']).chat('Portion?', self.nutrition5k)
        url = sent[0]['messages'][1]['content'][1]['image_url']['url']
        self.assertEqual(decode(url)[1].size, (256, 256))


if __name__ == '__main__':
    unittest.main()
