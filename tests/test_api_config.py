"""A2: OpenAI official API, key read only from .env (offline, no requests are sent)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import config  # noqa: E402
import chagApp_openai  # noqa: E402
import rag_food_code  # noqa: E402

# Decoys: none of these may reach a client.
SHELL_ENV = {'OPENAI_API_KEY': 'sk-from-shell',
             'OPENAI_BASE_URL': 'https://shell.invalid/v1',
             'OPENAI_API_BASE': 'https://shell.invalid/v1'}


class TestApiConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_path = os.path.join(self.tmp.name, '.env')

    def tearDown(self):
        self.tmp.cleanup()

    def write_env(self, text):
        with open(self.env_path, 'w') as f:
            f.write(text)

    def test_key_comes_from_env_file_not_shell(self):
        self.write_env('OPENAI_API_KEY=sk-from-dotenv\n')
        with mock.patch.dict(os.environ, SHELL_ENV):
            self.assertEqual(config.load_api_key(self.env_path), 'sk-from-dotenv')
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'sk-from-shell')  # .env not exported

    def test_chat_api_key_is_accepted(self):
        self.write_env('API_PROVIDER=openai\nCHAT_API_KEY=sk-chat\n')
        self.assertEqual(config.load_api_key(self.env_path), 'sk-chat')

    def test_missing_key_fails_loudly(self):
        self.write_env('OPENAI_API_KEY=\n')
        with mock.patch.dict(os.environ, SHELL_ENV):
            with self.assertRaises(RuntimeError):
                config.load_api_key(self.env_path)
        os.remove(self.env_path)
        with self.assertRaises(RuntimeError):
            config.load_api_key(self.env_path)

    def test_variable_references_are_rejected_not_expanded(self):
        # R-A2-1: python-dotenv would expand ${...} from the shell; no form may yield a key
        shell = {'OPENAI_API_KEY': 'sk-shell-only', 'CHAT_API_KEY': 'sk-shell-only', 'MY_KEY': 'sk-shell-only'}
        references = ['${OPENAI_API_KEY}', '"${OPENAI_API_KEY}"', '${CHAT_API_KEY}', '${MY_KEY}',
                      '${MY_KEY:-sk-default}', '$OPENAI_API_KEY']
        for name in ['OPENAI_API_KEY', 'CHAT_API_KEY']:
            for reference in references + ['${FILE_KEY}']:
                with self.subTest(name=name, reference=reference):
                    self.write_env(f'FILE_KEY=sk-in-file\n{name}={reference}\n')
                    with mock.patch.dict(os.environ, shell), \
                            mock.patch.object(config, 'ENV_PATH', self.env_path):
                        with self.assertRaises(RuntimeError) as raised:
                            config.load_api_key()
                        self.assertNotIn('sk-shell-only', str(raised.exception))
                        with self.assertRaises(RuntimeError):
                            chagApp_openai.Vision(config.MODELS['llm_vision'])
                        with self.assertRaises(RuntimeError):
                            rag_food_code.initialize_clients(config.MODELS)

    def test_clients_use_dotenv_key_and_official_endpoint(self):
        self.write_env('OPENAI_API_KEY=sk-from-dotenv\n')
        with mock.patch.dict(os.environ, SHELL_ENV), mock.patch.object(config, 'ENV_PATH', self.env_path):
            vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
            llm, llm_vision, embedding = rag_food_code.initialize_clients(config.MODELS)
        clients = {'Vision': vision.client, 'llm': llm.client._client,
                   'llm_vision': llm_vision.client._client, 'embedding': embedding.client._client}
        for name, client in clients.items():
            with self.subTest(client=name):
                self.assertEqual(client.api_key, 'sk-from-dotenv')
                self.assertEqual(str(client.base_url), 'https://api.openai.com/v1/')
        self.assertEqual(llm.model_name, config.MODELS['llm'])
        self.assertEqual(llm_vision.model_name, config.MODELS['llm_vision'])
        self.assertEqual(embedding.model, config.MODELS['embedding'])

    def test_dotenv_is_ignored_and_untracked(self):
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', '.env'], cwd=ROOT).returncode, 0)
        tracked = subprocess.run(['git', 'ls-files', '.env'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(tracked.stdout, '')

    def test_no_key_in_tracked_files(self):
        found = subprocess.run(['git', 'grep', '-nIE', r'sk-[A-Za-z0-9_-]{20,}'],
                               cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(found.stdout, '')

    def test_pipeline_has_no_azure_settings(self):
        for name in ['config.py', 'rag_food_code.py', 'chagApp_openai.py']:
            with self.subTest(script=name):
                self.assertNotIn('azure', (ROOT / 'code' / name).read_text().lower())


if __name__ == '__main__':
    unittest.main()
