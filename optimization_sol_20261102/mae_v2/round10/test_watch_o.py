import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import watch_o


class FollowerInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.scope=patch('opt_provider.ROOT',self.root)
        self.scope.start();self.addCleanup(self.scope.stop)
        (self.root/'launch').mkdir()
        (self.root/'runs/development').mkdir(parents=True)
        (self.root/'runs/development/completion.json').write_text('{}\n')

    def test_verify_completed_before_interruption_requires_manual_offline_continuation(self):
        log=self.root/'launch/automatic_verify.log'
        log.write_text('synthetic completed verification\n')
        with patch.object(watch_o,'ROUND',self.root),patch.object(watch_o.subprocess,'run') as call:
            with self.assertRaisesRegex(ValueError,'phase_log_already_exists'):
                watch_o.follow(123)
        call.assert_not_called()
        self.assertEqual(log.read_text(),'synthetic completed verification\n')
        self.assertFalse((self.root/'launch/automatic_score.log').exists())

    def test_failed_offline_verification_preserves_log_and_never_scores(self):
        with patch.object(watch_o,'ROUND',self.root), \
             patch.object(watch_o.subprocess,'run',return_value=SimpleNamespace(returncode=7)) as call:
            self.assertEqual(watch_o.follow(123),7)
        call.assert_called_once()
        command=call.call_args.args[0]
        self.assertEqual(command[:2],['unshare','-Urn'])
        self.assertEqual(command[-1],'verify')
        self.assertNotIn('--allow-paid',command)
        self.assertTrue((self.root/'launch/automatic_verify.log').is_file())
        self.assertFalse((self.root/'launch/automatic_score.log').exists())
        status=json.loads((self.root/'launch/automatic_followup.json').read_text())
        self.assertEqual(status['status'],'offline_verify_failed')
        self.assertEqual(status['new_paid_requests'],0)


if __name__=='__main__':unittest.main()
