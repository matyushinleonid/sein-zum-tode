import pytest

from sein_zum_tode.infrastructure.numbers import Num2WordsNumberSpeller

pytestmark = pytest.mark.fast


def test_spells_cardinal_numbers_in_each_supported_locale() -> None:
    subject = Num2WordsNumberSpeller.create()

    assert (
        subject.spell(120, "ru"),
        subject.spell(120, "en"),
    ) == (
        "сто двадцать",
        "one hundred and twenty",
    ), "number spelling lost its requested locale"
