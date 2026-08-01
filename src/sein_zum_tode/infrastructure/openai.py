from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import httpx
from openai import AsyncOpenAI
from openai.types.shared import ReasoningEffort
from openai.types.shared_params import Reasoning
from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Socks5Proxy:
    host: str
    port: int
    username: str
    password: str

    def url(self) -> httpx.URL:
        return httpx.URL(
            scheme="socks5h",
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )


@dataclass(frozen=True, slots=True)
class OpenAICompletionProfile:
    model: str
    reasoning_effort: ReasoningEffort
    max_output_tokens: int
    request_timeout_seconds: int
    system_prompt: str


class ParsedOpenAIResponse[ResponseT: BaseModel](Protocol):
    @property
    def output_parsed(self) -> ResponseT | None: ...


class OpenAIResponses[ResponseT: BaseModel](Protocol):
    def parse(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text_format: type[ResponseT],
        max_output_tokens: int,
        reasoning: Reasoning,
        store: Literal[False],
        timeout: int,
    ) -> Awaitable[ParsedOpenAIResponse[ResponseT]]: ...


class OpenAISdk[ResponseT: BaseModel](Protocol):
    @property
    def responses(self) -> OpenAIResponses[ResponseT]: ...

    def close(self) -> Awaitable[None]: ...


class AsyncOpenAISdkAdapter[ResponseT: BaseModel]:
    def __init__(self, sdk: AsyncOpenAI) -> None:
        self._sdk = sdk

    @property
    def responses(self) -> OpenAIResponses[ResponseT]:
        return self

    def parse(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text_format: type[ResponseT],
        max_output_tokens: int,
        reasoning: Reasoning,
        store: Literal[False],
        timeout: int,
    ) -> Awaitable[ParsedOpenAIResponse[ResponseT]]:
        return self._parse(
            model=model,
            instructions=instructions,
            input=input,
            text_format=text_format,
            max_output_tokens=max_output_tokens,
            reasoning=reasoning,
            store=store,
            request_timeout=timeout,
        )

    async def _parse(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text_format: type[ResponseT],
        max_output_tokens: int,
        reasoning: Reasoning,
        store: Literal[False],
        request_timeout: int,
    ) -> ParsedOpenAIResponse[ResponseT]:
        response = await self._sdk.responses.parse(
            model=model,
            instructions=instructions,
            input=input,
            text_format=text_format,
            max_output_tokens=max_output_tokens,
            reasoning=reasoning,
            store=store,
            timeout=request_timeout,
        )
        return cast(ParsedOpenAIResponse[ResponseT], response)

    async def close(self) -> None:
        await self._sdk.close()


class OpenAICompletionClient[ResponseT: BaseModel]:
    def __init__(
        self,
        *,
        sdk: OpenAISdk[ResponseT],
        profile: OpenAICompletionProfile,
        response_type: type[ResponseT],
    ) -> None:
        self._sdk = sdk
        self._profile = profile
        self._response_type = response_type

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def consumes_quota(self) -> bool:
        return True

    async def complete(self, *, user_prompt: str) -> ResponseT:
        response = await self._sdk.responses.parse(
            model=self._profile.model,
            instructions=self._profile.system_prompt,
            input=user_prompt,
            text_format=self._response_type,
            max_output_tokens=self._profile.max_output_tokens,
            reasoning=Reasoning(effort=self._profile.reasoning_effort),
            store=False,
            timeout=self._profile.request_timeout_seconds,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise TypeError("OpenAI response did not contain parsed structured output")
        return parsed

    async def close(self) -> None:
        await self._sdk.close()
