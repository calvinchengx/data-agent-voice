"""The host's turn policy, where it is decidable without a running graph.

`extension.py` imports the TEN runtime and cannot be unit-tested (pyproject
says so). What *can* be tested is `config.py` -- which is not a bag of settings
but the policy itself: which phrase is said for which outcome, and what each
switch means. Those are the claims docs/00-plan.md §7 and D9 make, and they are
the ones that would fail silently.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, path: pathlib.Path):
    package = "das_host"
    if package not in sys.modules:
        # A bare module object with a __path__, NOT the real package: its
        # __init__.py now imports the addon (which is what registers the
        # extension with the runtime), and the runtime is not installed here.
        # Executing it would fail collection for every test in this file.
        module = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec(package, None, is_package=True)
        )
        module.__path__ = [str(ROOT / "extensions" / package)]
        sys.modules[package] = module
    spec = importlib.util.spec_from_file_location(f"{package}.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{package}.{name}"] = module
    spec.loader.exec_module(module)
    return module


cfg = _load("config", ROOT / "extensions" / "das_host" / "config.py")


# ------------------------------------------------------------- the defaults --
def test_the_defaults_are_the_ci_shape():
    """CI has no GPU and no cache patch, so the defaults must be the state CI
    can actually run -- otherwise `make test` proves a configuration nobody
    exercises."""
    c = cfg.HostConfig()
    assert c.eou_mode == "fixed"
    assert c.speak_per_sentence is True
    assert c.prerendered_ack is True
    assert c.speculative_dispatch is False, "spends tokens on a guess; a demo switch"
    assert c.confirm_entities is True


@pytest.mark.parametrize(("mode", "semantic"), [("fixed", False), ("semantic", True), ("", False)])
def test_only_semantic_mode_defers_to_the_turn_detector(mode, semantic):
    """In fixed mode a final transcript ends the turn. In semantic mode the
    detector does, and a final transcript is only evidence -- treating both as
    decisions would take the turn twice."""
    assert cfg.HostConfig(eou_mode=mode).trust_turn_detection is semantic


@pytest.mark.parametrize(
    ("chunk", "per_sentence"), [("sentence", True), ("complete", False), ("", True)]
)
def test_chunking_off_means_waiting_for_the_whole_response(chunk, per_sentence):
    """Switch #4's audible 'before': the caller hears nothing until the model
    has finished. Anything but `complete` speaks as sentences land."""
    assert cfg.HostConfig(tts_chunk=chunk).speak_per_sentence is per_sentence


# ---------------------------------------------------- what is never composed --
def test_every_outcome_the_service_can_report_has_a_phrase():
    """D9: the model never sees a refusal, so a missing phrase is silence
    where the caller needed to be told they were refused."""
    c = cfg.HostConfig()
    for field in ("refusal_phrase", "abstention_phrase", "error_phrase", "ack_phrase"):
        assert getattr(c, field).strip(), field


def test_a_refusal_and_an_abstention_do_not_say_the_same_thing():
    """They are different events upstream for a reason: an abstention is a
    catalog gap a steward can act on, a refusal is a security event. A caller
    who hears the same sentence for both learns neither."""
    c = cfg.HostConfig()
    assert c.refusal_phrase != c.abstention_phrase != c.error_phrase


def test_the_refusal_phrase_does_not_pretend_the_data_is_missing():
    """The failure mode this whole design guards against: 'I couldn't find
    that' where the truth is 'you may not see it'."""
    said = cfg.HostConfig().refusal_phrase.lower()
    assert "access" in said or "permission" in said or "allowed" in said
    assert "not found" not in said and "no data" not in said


def test_the_phrases_are_short_enough_to_speak():
    """A caller cannot skim audio. Anything long enough to need skimming is
    the wrong shape for a fixed phrase."""
    c = cfg.HostConfig()
    for field in ("refusal_phrase", "abstention_phrase", "error_phrase", "ack_phrase"):
        assert len(getattr(c, field).split()) <= 14, field


def test_phrases_can_be_replaced_without_touching_code():
    """They are properties on the node, so a deployment can reword them --
    and a reworded refusal is still a fixed phrase, not model prose."""
    c = cfg.HostConfig(refusal_phrase="Not yours to see.")
    assert c.refusal_phrase == "Not yours to see."


# --------------------------------------------------- the fixed-phrase table --
def test_the_three_uncomposed_outcomes_map_to_configured_phrases():
    """The table in extension.py names config fields by string. A typo there
    is an AttributeError on the one turn that most needs to work."""
    ext = (ROOT / "extensions" / "das_host" / "extension.py").read_text()
    assert 'FIXED = {"refusal": "refusal_phrase"' in ext
    c = cfg.HostConfig()
    for field in ("refusal_phrase", "abstention_phrase", "error_phrase"):
        assert hasattr(c, field)


def test_the_host_speaks_through_one_path():
    """Every utterance goes out through `_say`. A second call to the TTS node
    from anywhere else in the file would be a second speaker with no arbiter."""
    ext = (ROOT / "extensions" / "das_host" / "extension.py").read_text()
    sends_to_tts = ext.count('"tts_text_input"')
    assert sends_to_tts == 1, "something other than _say is speaking"
