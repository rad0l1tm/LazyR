#!/usr/bin/env python3
"""Установка Page Reader с Silero TTS."""
import argparse
import asyncio
from pathlib import Path
import subprocess
import sys


def run(command):
    subprocess.run(command, check=True)


def install_models(root):
    from models import VoiceModels

    manager = VoiceModels(root / 'data', root / 'models')

    async def download_defaults():
        await manager.select('ru', 'aidar')
        await manager.select('en', 'en_0')

    asyncio.run(download_defaults())


def main():
    parser = argparse.ArgumentParser(
        description='Установка Page Reader (Silero TTS)'
    )
    parser.add_argument(
        '--skip-models',
        action='store_true',
        help='пропустить предварительную загрузку моделей Silero',
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent

    if sys.prefix == sys.base_prefix:
        print(
            'Сначала создайте и активируйте виртуальную среду. См. README.md.',
            file=sys.stderr,
        )
        return 1

    requirements = root / 'requirements.txt'
    if not requirements.is_file():
        print(f'Не найден файл зависимостей: {requirements}', file=sys.stderr)
        return 1

    print('Установка Python-зависимостей...')
    run([
        sys.executable,
        '-m',
        'pip',
        'install',
        '-r',
        str(requirements),
    ])

    print('Установка Chromium для Playwright...')
    run([
        sys.executable,
        '-m',
        'playwright',
        'install',
        'chromium',
    ])

    (root / 'models').mkdir(exist_ok=True)
    (root / 'data').mkdir(exist_ok=True)

    if not args.skip_models:
        print('Загрузка моделей Silero TTS...')
        install_models(root)
    else:
        print(
            'Загрузка моделей пропущена. '
            'Они будут скачаны при первом выборе голоса.'
        )

    print('Готово. Запуск: python app.py')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(
            'Установка прервана. Проверьте вывод выше и повторите команду.',
            file=sys.stderr,
        )
        sys.exit(exc.returncode)
    except Exception as exc:
        print(f'Ошибка установки Silero: {exc}', file=sys.stderr)
        sys.exit(1)