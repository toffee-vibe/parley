from datetime import datetime, timedelta

import pytest

from parley.domain.companion import Activity, Companion, EarsClosed
from parley.domain.conversation import Utterance
from parley.domain.learning import INTERVALS, LEARNED_STAGE, Mistake, MistakeKind, Phrase, ReviewOutcome
from parley.domain.speech import Speech, SpeechInterrupted, SpeechStatus

NOW = datetime(2026, 11, 21, 12, 0)


class TestCompanion:
    def test_without_claude_it_waits_and_does_not_listen(self):
        c = Companion()
        assert c.activity is Activity.WAITING and not c.listening
        c.user_started_talking(NOW)
        assert c.activity is Activity.WAITING  # слушать некому — не «слышит» и не «думает»
        c.partner_arrived(NOW)
        assert c.activity is Activity.IDLE and c.listening
        c.partner_left(NOW)
        assert c.activity is Activity.WAITING and not c.listening

    def test_muted_mic_survives_claude_coming_and_going(self):
        c = Companion()
        c.close_ears(NOW)
        c.partner_arrived(NOW)
        assert c.activity is Activity.DEAF and not c.listening
        c.open_ears(NOW)
        assert c.activity is Activity.IDLE and c.listening

    def test_waits_for_a_pause_before_speaking(self):
        c = Companion(partner_here=True, activity=Activity.IDLE)
        assert c.user_is_quiet(NOW, timedelta(seconds=1))
        c.user_started_talking(NOW)
        assert not c.user_is_quiet(NOW, timedelta(seconds=1))
        c.user_finished_talking(NOW, said_something=True)
        assert not c.user_is_quiet(NOW + timedelta(seconds=0.5), timedelta(seconds=1))
        assert c.user_is_quiet(NOW + timedelta(seconds=1.5), timedelta(seconds=1))

    def test_deaf_companion_ignores_voice_and_cannot_speak(self):
        c = Companion(partner_here=True, activity=Activity.IDLE)
        c.close_ears(NOW)
        assert isinstance(c.pull_events()[-1], EarsClosed)
        c.user_started_talking(NOW)
        assert c.activity is Activity.DEAF
        assert not c.can_speak()

    def test_noise_returns_to_idle_and_speech_to_thinking(self):
        c = Companion(partner_here=True, activity=Activity.IDLE)
        c.user_started_talking(NOW)
        c.user_finished_talking(NOW, said_something=False)
        assert c.activity is Activity.IDLE
        c.user_started_talking(NOW)
        c.user_finished_talking(NOW, said_something=True)
        assert c.activity is Activity.THINKING

    def test_thinking_does_not_last_forever(self):
        c = Companion(partner_here=True, activity=Activity.IDLE)
        c.user_started_talking(NOW)
        c.user_finished_talking(NOW, said_something=True)
        c.settle(NOW + timedelta(seconds=10), patience=timedelta(seconds=25))
        assert c.activity is Activity.THINKING
        c.settle(NOW + timedelta(seconds=30), patience=timedelta(seconds=25))
        assert c.activity is Activity.IDLE


class TestSpeech:
    def test_interrupt_reports_what_was_not_heard(self):
        s = Speech(text="Tell me about your last project please")
        s.begin(NOW)
        s.advance(len("Tell me ab"))  # слово "about" не дослушано
        assert s.user_started_talking(NOW)
        event = s.pull_events()[-1]
        assert isinstance(event, SpeechInterrupted)
        assert event.heard == "Tell me"
        assert event.not_heard == "about your last project please"

    def test_finished_speech_cannot_be_interrupted(self):
        s = Speech(text="Hi")
        s.begin(NOW)
        s.finish(NOW)
        assert not s.user_started_talking(NOW)
        assert s.status is SpeechStatus.FINISHED

    def test_queued_speech_is_dropped_and_tags_are_hidden(self):
        s = Speech(text="[excited] Wow! [curious] Tell me more.")
        assert s.clean_text == "Wow! Tell me more."
        s.user_started_talking(NOW)
        assert s.status is SpeechStatus.DROPPED

    def test_empty_text_is_rejected(self):
        with pytest.raises(ValueError):
            Speech(text="   ")


class TestUtterance:
    def test_language_is_measured_by_letters(self):
        assert Utterance("I worked on the backend", NOW, 2).language == "en"
        assert Utterance("я работал над бэкендом", NOW, 2).language == "ru"
        assert Utterance("I worked над бэкендом", NOW, 2).language == "mixed"

    def test_words_per_minute(self):
        assert Utterance("one two three four", NOW, 2).words_per_minute == 120


class TestPhrase:
    def test_success_moves_up_failure_moves_down(self):
        p = Phrase(text="I was responsible for", meaning="я отвечал за", example="", created_at=NOW)
        for _ in range(LEARNED_STAGE):
            p.review(ReviewOutcome.USED, NOW)
        assert p.learned
        p.review(ReviewOutcome.MISSED, NOW)
        assert not p.learned
        assert p.due_at == NOW + INTERVALS[p.stage]

    def test_new_phrase_comes_back_in_the_same_conversation(self):
        p = Phrase(text="to be honest", meaning="честно говоря", example="", created_at=NOW)
        assert not p.is_due(NOW)
        assert p.is_due(NOW + INTERVALS[0])


class TestMistake:
    def test_same_correct_form_is_one_mistake(self):
        m = Mistake(category=MistakeKind.GRAMMAR, wrong="I have worked there in 2020",
                    right="I worked there in 2020", explanation="", first_seen=NOW)
        m.happened("I have worked there in 2020", "past simple for finished time", NOW)
        m.happened("I has worked there in 2020", "", NOW)
        assert m.count == 2
        assert m.key == "i worked there in 2020"
        assert m.explanation == "past simple for finished time"


def test_monologue_is_refused_with_a_hint():
    import pytest

    from parley.domain.speech import MAX_SPOKEN_CHARS, Speech
    Speech("[warm] " + "a" * MAX_SPOKEN_CHARS)                    # теги не считаются
    with pytest.raises(ValueError, match="show_board"):
        Speech("Смотри. " * 60)
