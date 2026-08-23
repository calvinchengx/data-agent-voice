"""Deciding what the host is unsure it heard — phase 5, D12.

The class of error this exists for has no counterpart anywhere else in the
system: a perfectly formed question about the wrong subject. Every guard
downstream will pass it, and the answer will be confidently wrong. So the
tests are mostly about what does NOT get confirmed — a host that asks about
every capitalised word is unusable, and one nobody can bear to use protects
nothing.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, path: pathlib.Path):
    package = "das_host"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package, ROOT / "extensions" / package / "__init__.py"
        )
        module = importlib.util.module_from_spec(spec)
        module.__path__ = [str(ROOT / "extensions" / package)]
        sys.modules[package] = module
        spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location(f"{package}.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{package}.{name}"] = module
    spec.loader.exec_module(module)
    return module


t = _load("turn", ROOT / "extensions" / "das_host" / "turn.py")


# --------------------------------------------------------- what looks like a name --
@pytest.mark.parametrize("word", ["Billing", "Frontline", "ACME", "team-a", "Q4"])
def test_a_name_shaped_word_is_worth_confirming(word):
    assert t.nameish(word)


@pytest.mark.parametrize("word", ["the", "fastest", "resolve", "a", "of", "it"])
def test_an_ordinary_word_is_not(word):
    """Mishearing "fastest" produces a question that reads oddly. Mishearing
    "Billing" produces one that reads perfectly and is about someone else."""
    assert not t.nameish(word)


def test_punctuation_does_not_hide_a_name():
    assert t.nameish("Billing?") and t.nameish("Billing,")


# ------------------------------------------------------------ what gets flagged --
def test_a_low_confidence_name_is_flagged():
    said = "Which team resolves faster, Billing or Frontline?"
    terms = t.uncertain_terms(said, {"Billing": 0.31, "Frontline": 0.95})
    assert terms == ["Billing"]


def test_a_confident_name_is_not_flagged():
    assert t.uncertain_terms("Ask Billing", {"Billing": 0.99}) == []


def test_a_sentence_opener_is_never_flagged():
    """ "Which" is capitalised because a sentence started, not because it names
    anything. Confirming it would be asking the caller to repeat "which"."""
    assert t.uncertain_terms("Which team is fastest?", {"Which": 0.2, "team": 0.2}) == []


def test_nothing_is_flagged_without_per_word_confidence():
    """Most recognisers do not offer it. Guessing which words were uncertain
    would be worse than not asking: a confirmation at random trains the caller
    to ignore confirmations."""
    assert t.uncertain_terms("Which team, Billing or Frontline?") == []
    assert t.uncertain_terms("Billing", {}) == []


def test_a_flagged_term_appears_once_however_often_it_was_said():
    said = "Billing. I said Billing, not the other Billing."
    assert t.uncertain_terms(said, {"Billing": 0.2}) == ["Billing"]


def test_the_floor_is_adjustable_because_engines_disagree_about_scale():
    assert t.uncertain_terms("Billing", {"Billing": 0.7}) == []
    assert t.uncertain_terms("Billing", {"Billing": 0.7}, floor=0.8) == ["Billing"]


# ------------------------------------------------------------------- the hint --
def test_the_hint_states_a_fact_and_does_not_compose_the_question():
    """The model has a `confirm` tool and knows when to use it. This supplies
    only what it could not otherwise know."""
    hint = t.confirmation_hint(["Billing"])
    assert "'Billing'" in hint and "confirm" in hint
    assert "?" not in hint, "the question is the model's to ask"


def test_no_uncertain_term_means_no_hint():
    assert t.confirmation_hint([]) == ""


def test_several_terms_are_named_together():
    hint = t.confirmation_hint(["Billing", "Q4"])
    assert "'Billing'" in hint and "'Q4'" in hint


# ------------------------------------------------- speculative dispatch (switch #6) --
@pytest.mark.parametrize(
    "partial",
    ["Which team resolves tickets fastest?", "Show me revenue by quarter."],
    ids=["question", "statement"],
)
def test_a_whole_question_is_worth_guessing_on(partial):
    assert t.is_confident_partial(partial)


@pytest.mark.parametrize("partial", ["Which", "Which team", "um", ""])
def test_a_fragment_is_not(partial):
    """Every partial grows word by word, and each growth looks like a new
    chance to guess. A guess that is wrong costs a cancelled ask."""
    assert not t.is_confident_partial(partial)


def test_a_trailing_question_word_still_counts_as_an_opening():
    assert t.is_confident_partial("What was net revenue last year")


def test_the_host_guesses_at_most_once_per_turn():
    source = (ROOT / "extensions" / "das_host" / "extension.py").read_text()
    assert "self.speculated = True" in source
    assert "not self.speculated" in source


def test_confirmation_is_on_by_default_and_speculation_is_not():
    """The asymmetry is the point: confirming costs a second, guessing costs
    the caller's quota and a confused turn."""
    cfg = _load("config", ROOT / "extensions" / "das_host" / "config.py")
    c = cfg.HostConfig()
    assert c.confirm_entities is True
    assert c.speculative_dispatch is False
