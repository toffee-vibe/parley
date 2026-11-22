"""Настройки. Файл ~/.config/parley/config.toml создаётся при первом запуске — правь его, а не код.

Ключ OpenRouter можно положить в файл или в переменную окружения OPENROUTER_API_KEY.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "parley"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "parley"
CONFIG_FILE = CONFIG_DIR / "config.toml"
PROJECT_DIR = Path(__file__).resolve().parents[2]  # корень репозитория: здесь агенты подключаются к Parley

DEFAULT_CONFIG = """\
# Parley — настройки. После правки перезапусти приложение.

[openrouter]
api_key = ""                                       # или переменная окружения OPENROUTER_API_KEY
base_url = "https://openrouter.ai/api/v1"
# Распознавание. gpt-4o-mini-transcribe (~$0.11 за час твоей речи; тишина не отправляется) не переводит
# смешанную речь: «Ну, I worked…» остаётся как сказано. Whisper такое переводит целиком на один язык.
# Дешевле в 9 раз, но хуже со смешанной речью: "openai/whisper-large-v3-turbo".
transcription_model = "openai/gpt-4o-mini-transcribe"
# Подсказка распознаванию: слова, которые оно должно знать (имена, техника из твоих рассказов).
transcription_prompt = "English speaking practice with Parley (Pip). The speaker is Russian and mixes English and Russian: keep every word in the language it was spoken, do not translate. Transcribe verbatim: keep grammar mistakes exactly as spoken. Python, backend, PostgreSQL, FastAPI, Docker, deploy."
fallback_transcription_model = "openai/whisper-large-v3-turbo"  # если основная отказала (лимит запросов, сбой)
voice_model = "fish-audio/s2.1-pro-free:free"      # бесплатно; пусто — только локальный голос

[voice]
# Два голоса-носителя из библиотеки Fish Audio (fish.audio → Voice Library, id из адреса страницы голоса).
# Английские куски фразы говорит английский голос, русские — русский: без акцента в обе стороны.
english = "711cf3ed00ab441a8f54a45058047b7a"   # «Verity» (en): молодой, дружелюбный, живой
russian = "850f1009b2f54e4483e3a7f3eb558bb4"   # «Verity» (ru): такой же характер, по-русски
volume = 0.6                         # 0..1; ползунок в окне запоминает своё значение
fallback_en = "en_US-ryan-medium"     # локальный Piper, если облачный голос недоступен
fallback_ru = "ru_RU-dmitri-medium"
output = ""                          # колонки: имя выхода PipeWire или часть имени устройства (Windows/macOS); пусто — по умолчанию

[transcription]
# Кто распознаёт твою речь:
#   auto  — облако, если задан ключ OpenRouter, иначе встроенная модель (по умолчанию)
#   cloud — облако (OpenRouter, модель выше): точнее всего, ~$0.11 за час твоей речи
#   local — встроенная модель на этом компьютере: бесплатно и без сети; один раз скачивается ~500 МБ
# Если облако не ответило (нет сети, кончились деньги) — фраза уходит во встроенную модель.
engine = "auto"
# Встроенная модель: parakeet (Parakeet TDT 0.6b v3: русский, английский и смесь; ~0.3 с на фразу)
#                    whisper-turbo (чуть хуже на смешанной речи и в ~10 раз медленнее)
local_model = "parakeet"

[hearing]
input = ""                # микрофон: имя источника PipeWire или часть имени устройства (Windows/macOS); пусто — по умолчанию
vad_threshold = 0.5       # чувствительность детектора речи (0..1)
end_of_phrase_s = 0.8     # пауза, после которой фраза считается законченной
echo_margin = 2.5         # во сколько раз голос должен быть громче эха колонок, чтобы засчитать перебивание
sounds = true             # распознавать звуки: смех, кашель, клавиатура, музыка…
sound_threshold = 0.4
sound_cooldown_s = 10     # один и тот же звук — не чаще раза в N секунд

[conversation]
turn_end_s = 2.5          # сколько молчать, чтобы мысль считалась законченной и ушла агенту; не успеваешь договорить — увеличь
reply_pause_s = 1.2       # сколько молчать после твоей фразы, прежде чем отвечать (не перебивать тебя)

[server]
host = "127.0.0.1"
port = 8790
"""


@dataclass
class OpenRouterSettings:
    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    transcription_model: str = "openai/gpt-4o-mini-transcribe"
    transcription_prompt: str = ("English speaking practice with Parley (Pip). The speaker is Russian and mixes English "
                                 "and Russian: keep every word in the language it was spoken, do not translate. "
                                 "Transcribe verbatim: keep grammar mistakes exactly as spoken. "
                                 "Python, backend, PostgreSQL, FastAPI, Docker, deploy.")
    fallback_transcription_model: str = "openai/whisper-large-v3-turbo"
    voice_model: str = "fish-audio/s2.1-pro-free:free"


@dataclass
class VoiceSettings:
    english: str = "711cf3ed00ab441a8f54a45058047b7a"
    russian: str = "850f1009b2f54e4483e3a7f3eb558bb4"
    volume: float = 0.6
    fallback_en: str = "en_US-ryan-medium"
    fallback_ru: str = "ru_RU-dmitri-medium"
    output: str = ""


@dataclass
class TranscriptionSettings:
    engine: str = "auto"            # auto | cloud | local
    local_model: str = "parakeet"   # parakeet | whisper-turbo


@dataclass
class HearingSettings:
    input: str = ""
    vad_threshold: float = 0.5
    end_of_phrase_s: float = 0.8
    echo_margin: float = 2.5
    sounds: bool = True
    sound_threshold: float = 0.4
    sound_cooldown_s: float = 10.0


@dataclass
class ConversationSettings:
    turn_end_s: float = 2.5       # сколько молчать, чтобы мысль считалась законченной и ушла агенту
    reply_pause_s: float = 1.2


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8790

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class Settings:
    openrouter: OpenRouterSettings = field(default_factory=OpenRouterSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    hearing: HearingSettings = field(default_factory=HearingSettings)
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    conversation: ConversationSettings = field(default_factory=ConversationSettings)
    server: ServerSettings = field(default_factory=ServerSettings)

    @property
    def models_dir(self) -> Path:
        return DATA_DIR / "models"

    @property
    def database(self) -> Path:
        return DATA_DIR / "parley.db"

    @property
    def diary_dir(self) -> Path:
        """Технический дневник: как работало приложение (infrastructure/diary.py, `parley report`)."""
        return DATA_DIR / "diary"


def load() -> Settings:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
    raw = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    settings = Settings(
        openrouter=_section(OpenRouterSettings, raw.get("openrouter")),
        voice=_section(VoiceSettings, raw.get("voice")),
        hearing=_section(HearingSettings, raw.get("hearing")),
        transcription=_section(TranscriptionSettings, raw.get("transcription")),
        conversation=_section(ConversationSettings, raw.get("conversation")),
        server=_section(ServerSettings, raw.get("server")),
    )
    settings.openrouter.api_key = os.environ.get("OPENROUTER_API_KEY") or settings.openrouter.api_key
    return settings


def _section[T](cls: type[T], values: dict[str, Any] | None) -> T:
    """Неизвестные ключи игнорируем, чтобы старый конфиг не ломал новую версию."""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (values or {}).items() if k in known})
