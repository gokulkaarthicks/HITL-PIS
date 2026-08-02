"""Tests for requirements applied to every model request."""

from app.llm import build_system_prompt
from app.prompt_contract import ENGLISH_OUTPUT_INSTRUCTION


def test_runtime_prompt_adds_english_requirement_to_existing_prompt():
    prompt = build_system_prompt("Existing active prompt")

    assert prompt.endswith(ENGLISH_OUTPUT_INSTRUCTION)


def test_runtime_prompt_does_not_duplicate_english_requirement():
    prompt = build_system_prompt(f"Existing prompt\n\n{ENGLISH_OUTPUT_INSTRUCTION}")

    assert prompt.count(ENGLISH_OUTPUT_INSTRUCTION) == 1
