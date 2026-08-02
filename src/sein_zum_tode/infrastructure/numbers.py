from importlib import import_module
from typing import Protocol, Self, cast


class Num2WordsSdk(Protocol):
    def __call__(self, value: int, *, lang: str) -> str: ...


class Num2WordsNumberSpeller:
    def __init__(self, sdk: Num2WordsSdk) -> None:
        self._sdk = sdk

    @classmethod
    def create(cls) -> Self:
        sdk = cast(Num2WordsSdk, vars(import_module("num2words"))["num2words"])
        return cls(sdk)

    def spell(self, value: int, locale: str) -> str:
        return self._sdk(value, lang=locale)
