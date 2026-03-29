"""
LLM helper — wraps Groq calls with retry/backoff for free-tier rate limits.
Import `get_llm` and `invoke_with_retry` instead of using ChatGroq directly.
"""
import os
import asyncio
from langchain_groq import ChatGroq


# Groq free-tier limits: 30 RPM, 6000 TPM, 1000 RPD
MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # seconds to wait on rate limit


def get_llm():
    """Returns a configured ChatGroq instance."""
    return ChatGroq(model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))


async def invoke_with_retry(llm, messages, label="llm"):
    """
    Calls llm.ainvoke with automatic retry on rate limit errors.
    Returns the response content string.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await llm.ainvoke(messages)
            return response.content.strip()
        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str or "429" in error_str or "too many" in error_str:
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAYS[attempt]
                    print(f"[{label}] Rate limited — retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
                    await asyncio.sleep(wait)
                else:
                    print(f"[{label}] Rate limit exceeded after {MAX_RETRIES} retries — skipping")
                    raise
            else:
                raise
