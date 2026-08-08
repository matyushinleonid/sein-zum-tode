from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal
from unittest.mock import Mock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from openai.types.shared_params import Reasoning
from pydantic import BaseModel

from sein_zum_tode.infrastructure.openai import (
    AsyncOpenAISdkAdapter,
    OpenAICompletionClient,
    OpenAICompletionProfile,
    Socks5Proxy,
    classify_openai_error,
)
from sein_zum_tode.ports.completion import CompletionErrorKind, CompletionFailure

pytestmark = pytest.mark.fast


def openai_status_error[ErrorT: APIStatusError](error_type: type[ErrorT], status: int) -> ErrorT:
    return error_type(
        "boom",
        response=httpx.Response(
            status,
            request=httpx.Request("POST", "https://api.openai.com"),
        ),
        body=None,
    )


class ExplodingOpenAISdkDouble:
    @property
    def responses(self) -> ExplodingOpenAISdkDouble:
        return self

    async def parse(self, **options: object) -> object:
        raise openai_status_error(RateLimitError, 429)

    async def close(self) -> None:
        return None


class CompletionResult(BaseModel):
    value: int
    explanation: str


@dataclass(frozen=True, slots=True)
class ParsedResponseDouble:
    output_parsed: CompletionResult | None


class ResponsesDouble:
    def __init__(self, parsed: CompletionResult | None) -> None:
        self._parsed = parsed
        self.events: list[dict[str, object]] = []

    def parse(
        self,
        *,
        model: str,
        instructions: str,
        input: str,
        text_format: type[CompletionResult],
        max_output_tokens: int,
        reasoning: Reasoning,
        store: Literal[False],
        timeout: int,
    ) -> Awaitable[ParsedResponseDouble]:
        self.events.append(
            {
                "model": model,
                "instructions": instructions,
                "input": input,
                "text_format": text_format,
                "max_output_tokens": max_output_tokens,
                "reasoning": reasoning,
                "store": store,
                "timeout": timeout,
            }
        )
        return self._response()

    async def _response(self) -> ParsedResponseDouble:
        return ParsedResponseDouble(output_parsed=self._parsed)


class OpenAISdkDouble:
    def __init__(self, parsed: CompletionResult | None) -> None:
        self.responses = ResponsesDouble(parsed)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def profile() -> OpenAICompletionProfile:
    return OpenAICompletionProfile(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        max_output_tokens=3877,
        request_timeout_seconds=83,
        system_prompt="Return a structured result",
    )


def adapter(
    sdk: OpenAISdkDouble | ExplodingOpenAISdkDouble,
) -> AsyncOpenAISdkAdapter[CompletionResult]:
    typed_sdk = Mock(spec=AsyncOpenAI)
    typed_sdk.responses = sdk.responses
    typed_sdk.close = sdk.close
    return AsyncOpenAISdkAdapter[CompletionResult](typed_sdk)


async def test_enforces_the_adapter_schema_and_disables_response_storage() -> None:
    sdk = OpenAISdkDouble(CompletionResult(value=3881, explanation="Structured"))
    client = OpenAICompletionClient(
        sdk=adapter(sdk),
        profile=profile(),
        response_type=CompletionResult,
    )

    actual = await client.complete(user_prompt="Current date and answers")
    await client.close()

    assert (
        sdk.responses.events,
        client.provider_name,
        client.consumes_quota,
        actual,
        sdk.closed,
    ) == (
        [
            {
                "model": "gpt-5.6-sol",
                "instructions": "Return a structured result",
                "input": "Current date and answers",
                "text_format": CompletionResult,
                "max_output_tokens": 3877,
                "reasoning": {"effort": "medium"},
                "store": False,
                "timeout": 83,
            }
        ],
        "openai",
        True,
        CompletionResult(value=3881, explanation="Structured"),
        True,
    ), "OpenAI adapter skipped its schema, proxy-safe storage setting, or lifecycle"


async def test_rejects_an_openai_response_without_parsed_output() -> None:
    client = OpenAICompletionClient(
        sdk=adapter(OpenAISdkDouble(None)),
        profile=profile(),
        response_type=CompletionResult,
    )

    with pytest.raises(CompletionFailure) as failure:
        await client.complete(user_prompt="Unparseable")

    assert failure.value.kind is CompletionErrorKind.INVALID_RESPONSE, (
        "an unparseable OpenAI response was not reported as an invalid response"
    )


def test_builds_a_dns_proxied_authenticated_socks5_url() -> None:
    url = Socks5Proxy(
        host="167.233.46.190",
        port=32768,
        username="matyushinleonid",
        password="irregular p@ssword",
    ).url()

    assert (
        url.scheme,
        url.host,
        url.port,
        url.username,
        url.password,
    ) == (
        "socks5h",
        "167.233.46.190",
        32768,
        "matyushinleonid",
        "irregular p@ssword",
    ), "proxy URL bypassed proxied DNS or lost its endpoint credentials"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")), "timeout"),
        (
            APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")),
            "connection",
        ),
        (openai_status_error(RateLimitError, 429), "rate_limit"),
        (openai_status_error(AuthenticationError, 401), "authentication"),
        (openai_status_error(PermissionDeniedError, 403), "authentication"),
        (openai_status_error(BadRequestError, 400), "bad_request"),
        (openai_status_error(UnprocessableEntityError, 422), "bad_request"),
        (openai_status_error(NotFoundError, 404), "bad_request"),
        (openai_status_error(InternalServerError, 500), "server_error"),
        (ValueError("proxy exploded"), "unknown"),
    ],
)
def test_classifies_every_openai_failure_into_a_bounded_error_kind(
    error: Exception,
    expected: str,
) -> None:
    assert classify_openai_error(error).value == expected, (
        "an OpenAI failure was classified into the wrong bounded error kind"
    )


async def test_reports_a_failing_openai_call_as_a_classified_completion_failure() -> None:
    client = OpenAICompletionClient(
        sdk=adapter(ExplodingOpenAISdkDouble()),
        profile=profile(),
        response_type=CompletionResult,
    )

    with pytest.raises(CompletionFailure) as failure:
        await client.complete(user_prompt="Doomed")

    assert (failure.value.provider, failure.value.kind) == (
        "openai",
        CompletionErrorKind.RATE_LIMIT,
    ), "a rate-limited OpenAI call did not surface as a classified completion failure"
