"""The superseded N5-only CLI must not start an accidental paid experiment."""
import contextlib
import io
import unittest
from unittest.mock import patch

from round6.src import run_pilot


class ShelvedCliTests(unittest.TestCase):
    def test_base_cannot_load_data_or_construct_provider(self):
        with patch.object(run_pilot.context, 'load_context') as load, \
             patch.object(run_pilot, 'PilotProvider') as provider, \
             patch.object(run_pilot, 'base') as base, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run_pilot.main(['base', '--allow-paid']), 2)
        load.assert_not_called()
        provider.assert_not_called()
        base.assert_not_called()
        self.assertIn('"status": "stopped"', output.getvalue())


if __name__ == '__main__':
    unittest.main()
