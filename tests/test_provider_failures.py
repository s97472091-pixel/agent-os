from __future__ import annotations

from agentos.provider.failures import ProviderFailureKind, classify_provider_error


def test_provider_request_budget_exhausted_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="openrouter",
            status_code=None,
            raw_code="provider_request_budget_exhausted",
            message='{"fallback_reason":"provider_request_budget_exhausted"}',
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_gemini_input_token_count_message_is_context_overflow() -> None:
    """Gemini's real context-overflow error should be classified as CONTEXT_OVERFLOW."""
    assert (
        classify_provider_error(
            provider_name="gemini",
            status_code=400,
            message=(
                "the input token count (12345) exceeds the maximum number of tokens allowed (8192)."
            ),
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_anthropic_prompt_too_long_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=400,
            raw_code="prompt_too_long",
            message="prompt_too_long: prompt is longer than the maximum allowed length",
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_gemini_input_token_count_message_is_context_overflow_different_counts() -> None:
    """Same message with different token counts must still match."""
    assert (
        classify_provider_error(
            provider_name="gemini",
            status_code=400,
            message=(
                "the input token count (512) exceeds the maximum number of tokens allowed (4096)."
            ),
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_anthropic_exceed_context_limit_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=400,
            raw_code="invalid_request_error",
            message="input length and max_tokens exceed context limit: 200000 > 199999",
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_anthropic_request_too_large_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=413,
            raw_code="request_too_large",
            message="request_too_large: request body is too large",
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_anthropic_request_size_exceeds_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=413,
            raw_code="invalid_request_error",
            message="request size exceeds the 131072 byte limit",
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


# ── #775: bankr in OpenAI-compat set ────────────────────────────────────


def test_bankr_401_is_auth_invalid() -> None:
    assert (
        classify_provider_error("bankr", 401, message="Unauthorized")
        is ProviderFailureKind.AUTH_INVALID
    )


def test_bankr_402_is_insufficient_credits() -> None:
    assert (
        classify_provider_error("bankr", 402, message="Insufficient credits")
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_bankr_429_is_rate_limited() -> None:
    assert (
        classify_provider_error("bankr", 429, message="Rate limit exceeded")
        is ProviderFailureKind.RATE_LIMITED
    )


def test_volcengine_coding_plan_401_is_auth_invalid() -> None:
    assert (
        classify_provider_error("volcengine_coding_plan", 401, message="Unauthorized")
        is ProviderFailureKind.AUTH_INVALID
    )


def test_byteplus_coding_plan_429_is_rate_limited() -> None:
    assert (
        classify_provider_error("byteplus_coding_plan", 429, message="Rate limit exceeded")
        is ProviderFailureKind.RATE_LIMITED
    )


# ── #777: credit/quota exhaustion → INSUFFICIENT_CREDITS ─────────────────


def test_openai_insufficient_quota_429_is_insufficient_credits() -> None:
    """insufficient_quota with HTTP 429 must not be swallowed by the rate-limit branch."""
    assert (
        classify_provider_error(
            provider_name="openai",
            status_code=429,
            raw_code="insufficient_quota",
            message="You exceeded your current quota, please check your plan and billing details.",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_openai_quota_exceeded_message_is_insufficient_credits() -> None:
    """Quota message without raw_code should still be caught."""
    assert (
        classify_provider_error(
            provider_name="openai",
            status_code=429,
            message="You exceeded your current quota.",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_openrouter_insufficient_quota_is_insufficient_credits() -> None:
    assert (
        classify_provider_error(
            provider_name="openrouter",
            status_code=429,
            raw_code="insufficient_quota",
            message="Insufficient quota",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_deepseek_insufficient_quota_is_insufficient_credits() -> None:
    assert (
        classify_provider_error(
            provider_name="deepseek",
            status_code=429,
            raw_code="insufficient_quota",
            message="Insufficient quota",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_anthropic_billing_error_402_is_insufficient_credits() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=402,
            raw_code="billing_error",
            message="Your credit balance is too low to access the Anthropic API.",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_anthropic_bare_402_is_insufficient_credits() -> None:
    """A bare HTTP 402 with no marker text must still resolve to INSUFFICIENT_CREDITS."""
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=402,
            message="Payment Required",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_anthropic_credit_balance_too_low_is_insufficient_credits() -> None:
    assert (
        classify_provider_error(
            provider_name="anthropic",
            status_code=None,
            message="Your credit balance is too low to access the Anthropic API.",
        )
        is ProviderFailureKind.INSUFFICIENT_CREDITS
    )


def test_genuine_429_rate_limit_still_rate_limited() -> None:
    """A genuine rate-limit 429 without quota markers must still be RATE_LIMITED."""
    assert (
        classify_provider_error(
            provider_name="openai",
            status_code=429,
            message="Rate limit exceeded, please wait and retry.",
        )
        is ProviderFailureKind.RATE_LIMITED
    )


def test_policy_refusal_not_misread_as_insufficient_credits() -> None:
    """Policy refusal markers must win over any accidental credit marker match."""
    assert (
        classify_provider_error(
            provider_name="openai",
            status_code=400,
            message="Your content violates our safety policy.",
        )
        is ProviderFailureKind.POLICY_REFUSAL
    )
