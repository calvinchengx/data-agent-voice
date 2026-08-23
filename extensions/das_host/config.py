"""What the host is allowed to do, as configuration.

Every switch in `docs/00-plan.md` §10 that belongs to the turn arrives here.
They are settings rather than constants because the demo turns them off and on
in front of an audience and the panel measures the difference -- a lever the
audience cannot hear is a claim, not a demonstration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HostConfig(BaseModel):
    greeting: str = Field(
        default="", description="spoken once when the first caller joins; empty says nothing"
    )

    # --- the switches -------------------------------------------------------
    eou_mode: str = Field(
        default="fixed",
        description="fixed: VAD plus ASR finality. semantic: the turn-detection node decides.",
    )
    tts_chunk: str = Field(
        default="sentence",
        description="sentence: speak each sentence as it completes. complete: wait for the "
        "whole response, which is the 'off' state of switch #4 and sounds like it.",
    )
    prerendered_ack: bool = Field(
        default=True,
        description="say a pre-rendered acknowledgement the moment a question is dispatched, "
        "instead of waiting for the model to compose one",
    )
    speculative_dispatch: bool = Field(default=False)
    confirm_entities: bool = Field(default=True)

    # --- what the host says when the service says something ------------------
    # Bound to event types, never composed by the model. A refusal smoothed
    # into plausible prose is the failure the service upstream exists to
    # prevent, and the only way to make that impossible rather than unlikely
    # is for the model never to see the text (docs/00-plan.md D9).
    ack_phrase: str = Field(default="Let me work that out.")
    refusal_phrase: str = Field(default="You don't have access to that, so I can't answer it.")
    abstention_phrase: str = Field(default="I looked, and the data can't answer that one.")
    error_phrase: str = Field(default="Something went wrong on my side.")

    @property
    def speak_per_sentence(self) -> bool:
        return self.tts_chunk != "complete"

    @property
    def trust_turn_detection(self) -> bool:
        return self.eou_mode == "semantic"
