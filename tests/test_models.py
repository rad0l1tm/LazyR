import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from models import VoiceModels

class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_is_saved_after_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = VoiceModels(root, root/'models')
            loader = Mock(return_value=object())
            with patch.dict('sys.modules', {'piper':types.SimpleNamespace(PiperVoice=types.SimpleNamespace(load=loader))}):
                await models.select('ru', 'ru_RU-irina-medium')
            self.assertEqual(VoiceModels(root, root/'models').selected['ru'], 'ru_RU-irina-medium')
            loader.assert_called_once()
            with self.assertRaises(ValueError):
                await models.select('ru', '../../unexpected')
            self.assertEqual(models.selected['ru'], 'ru_RU-irina-medium')
