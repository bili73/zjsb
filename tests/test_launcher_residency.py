import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ocr_app.launcher import launch


class LauncherResidencyTests(unittest.TestCase):
    def test_legacy_single_preference_migrates_to_dual_without_database_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.runtime').mkdir()
            settings = root/'.runtime/settings.json'
            settings.write_text(json.dumps({'mode':'single_resident'}))
            with patch('ocr_app.launcher.ROOT', root), patch('sys.argv',['launch','--no-browser']), \
                 patch('ocr_app.business.Business') as business, patch('ocr_app.client.RuntimeClient') as client, \
                 patch('ocr_app.api.create_app'), patch('uvicorn.Server'):
                business.return_value.root = root/'.runtime/data'
                launch(Mock())
            self.assertEqual(client.call_args.args[0].mode, 'dual_resident')
            self.assertEqual(json.loads(settings.read_text()), {'mode':'dual_resident'})
            client.return_value.close.assert_called_once()

    def test_single_mode_is_not_a_production_cli_option(self):
        with patch('sys.argv',['launch','--mode','single_resident']), self.assertRaises(SystemExit) as error:
            launch(Mock())
        self.assertEqual(error.exception.code,2)
