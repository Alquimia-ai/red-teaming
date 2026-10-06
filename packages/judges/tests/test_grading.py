"""Grade provider replies through the real logprob grader, including reasoning envelopes."""

import math

import pytest
from gaussia.core.exceptions import LogprobsExtractionError
from gaussia.schemas.roastme import Principle
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from redteam_judges.grading import build_grader


@pytest.mark.parametrize("verdict", ["YES", "NO"])
def test_a_verdict_attached_to_the_reasoning_close_uses_its_own_logprobs(verdict: str) -> None:
    alternatives = [
        {"token": "YES", "logprob": math.log(0.2)},
        {"token": "NO", "logprob": math.log(0.8)},
    ]
    reply = AIMessage(
        content=f"Consider YES. I will answer {verdict}.</think>{verdict}",
        response_metadata={
            "finish_reason": "stop",
            "logprobs": {
                "content": [
                    {"token": "YES", "top_logprobs": [{"token": "YES", "logprob": 0.0}]},
                    {"token": "</think>"},
                    {"token": verdict, "top_logprobs": alternatives},
                ]
            },
        },
    )
    grader = build_grader(FakeMessagesListChatModel(responses=[reply]))
    principle = Principle(id="p", weight=1.0, rubric="Do not invent facts.", grader=grader)

    grade = grader.grade("question", "answer", principle)

    assert grade.method == "logprob-last-verdict-token"
    assert grade.score == pytest.approx(0.2)
    assert grade.evidence["final_answer"] == verdict
    assert grade.evidence["position"] == 2
    assert grade.evidence["top_logprobs"] == alternatives
    assert reply.content == f"Consider YES. I will answer {verdict}.</think>{verdict}"


@pytest.mark.parametrize(
    ("content", "tokens", "finish_reason"),
    [
        ("<think>Still considering YES", ["<think>", "YES"], "length"),
        ("<think>Still considering YES", ["<think>", "YES"], "stop"),
        ("NO", ["NO"], "length"),
        ("Consider YES</think>NO", ["YES", "</think>"], "stop"),
        ("Consider YES</think>NO", ["YES"], "stop"),
        ("Consider YES</think>", ["YES", "</think>"], "stop"),
    ],
)
def test_reasoning_tokens_cannot_substitute_for_a_final_verdict(
    content: str, tokens: list[str], finish_reason: str
) -> None:
    reply = AIMessage(
        content=content,
        response_metadata={
            "finish_reason": finish_reason,
            "logprobs": {
                "content": [
                    {"token": token, "top_logprobs": [{"token": "YES", "logprob": 0.0}]}
                    for token in tokens
                ]
            },
        },
    )
    grader = build_grader(FakeMessagesListChatModel(responses=[reply]))
    principle = Principle(id="p", weight=1.0, rubric="Do not invent facts.", grader=grader)

    with pytest.raises(LogprobsExtractionError):
        grader.grade("question", "answer", principle)


@pytest.mark.parametrize("verdict", ["YES", "NO"])
def test_plain_final_answers_keep_the_existing_logprob_path(verdict: str) -> None:
    reply = AIMessage(
        content=verdict,
        response_metadata={
            "finish_reason": "stop",
            "logprobs": {
                "content": [
                    {"token": verdict, "top_logprobs": [{"token": verdict, "logprob": 0.0}]}
                ]
            },
        },
    )
    grader = build_grader(FakeMessagesListChatModel(responses=[reply]))
    principle = Principle(id="p", weight=1.0, rubric="Do not invent facts.", grader=grader)

    grade = grader.grade("question", "answer", principle)

    assert grade.method == "logprob-last-verdict-token"
    assert grade.score == (1.0 if verdict == "YES" else 0.0)
    assert grade.evidence["final_answer"] == verdict
