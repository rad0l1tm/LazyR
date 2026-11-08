import asyncio
import json
import tempfile
import wave
import io

from pathlib import Path


# Silero TTS catalog
CATALOG = {
    'ru': {
        'model': 'v5_6_ru',
        'speakers': [
            'aidar',
            'baya',
            'kseniya',
            'xenia',
            'eugene',
        ],
        'sample_rate': 48000,
    },
    'en': {
        'model': 'v3_en',
        'speakers': [
            'en_0',
            'en_1',
        ],
        'sample_rate': 48000,
    },
}


class VoiceModels:

    def __init__(self, data_dir, model_dir):
        self.directory = Path(model_dir)
        self.settings = Path(data_dir) / 'voices.json'

        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings.parent.mkdir(parents=True, exist_ok=True)

        self.selected = {
            lang: config['speakers'][0]
            for lang, config in CATALOG.items()
        }

        self.models = {}

        try:
            saved = json.loads(self.settings.read_text(encoding='utf-8'))

            self.selected.update({
                k: v
                for k, v in saved.items()
                if k in CATALOG and v in CATALOG[k]['speakers']
            })

        except (OSError, ValueError):
            pass

    def _load_model(self, lang):
        import torch

        config = CATALOG[lang]

        torch.hub.set_dir(str(self.directory / '.torch_hub'))

        model, example_text = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language=lang,
            speaker=config['model'],
            trust_repo=True,
        )

        model.to(torch.device('cpu'))

        # У Silero TTSModelMultiAcc_v3 нет метода eval().
        # Переводим внутреннюю PyTorch-модель в режим eval,
        # если она доступна.
        if hasattr(model, 'eval'):
            model.eval()

        return model

    async def get_model(self, lang):

        if lang not in CATALOG:
            raise ValueError('Неизвестный язык')

        if lang not in self.models:
            model = await asyncio.to_thread(
                self._load_model,
                lang
            )

            self.models[lang] = model

        return self.models[lang]

    def describe(self):

        result = {}

        for lang, config in CATALOG.items():

            marker = self.directory / f'{config["model"]}.ready'

            installed = marker.is_file()

            result[lang] = [
                {
                    'name': speaker,
                    'installed': installed,
                }
                for speaker in config['speakers']
            ]

        return {
            'selected': self.selected,
            'catalog': result,
        }

    async def select(self, lang, name):

        if lang not in CATALOG or name not in CATALOG[lang]['speakers']:
            raise ValueError('Неизвестная модель голоса')

        # Load and validate model before changing selection.
        model = await self.get_model(lang)

        if model is None:
            raise RuntimeError('Не удалось загрузить модель Silero')

        # Mark model as installed only after successful loading.
        config = CATALOG[lang]

        marker = self.directory / f'{config["model"]}.ready'
        temporary_marker = marker.with_suffix('.tmp')

        temporary_marker.write_text('ok', encoding='utf-8')
        temporary_marker.replace(marker)

        # Atomic settings update.
        selected = {
            **self.selected,
            lang: name,
        }

        temporary = self.settings.with_suffix('.tmp')

        temporary.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        temporary.replace(self.settings)

        self.selected = selected