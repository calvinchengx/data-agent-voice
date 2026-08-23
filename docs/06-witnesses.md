# What is checked, and what that is worth

159 checks run on every push. **None of them can tell you the line works** —
only a call does that, and [`parity.md`](parity.md) keeps those rows red.

What they can tell you is that the configuration agrees with itself, and every
one of those agreements has been got wrong at least once.

## The groups

| Group | Checks | What it would catch |
|---|---|---|
| the graph | every addon declared; the host is the only path to the model; `mcp_client_python` absent; barge-in reaches all three; an extension registers its addon | a node that installs nothing; a second way to answer a data question |
| backends | every configured backend has a descriptor; each declares its dispatch and budgets; no general layer names one service's vocabulary | a dispatch tool that silently never registers, so the model answers from its own knowledge |
| the host's policy | a phrase for every outcome; refusal ≠ abstention ≠ error; the refusal says *access*; phrases short enough to speak | a refusal that sounds like missing data |
| what was misheard | name shapes; openers never flagged; nothing flagged without confidence; the hint states a fact | a host that asks about every capitalised word |
| the bridge | answer order; a table never read out; caveats capped; **the renderer has no words for a refusal** | the model being handed a refusal to reword |
| the panel | p95 by nearest rank; a span needs both marks; the first mark wins; nothing stored | a number no turn actually took |
| settings and pins | every setting the graph reads is in the template; every switch is a setting; the TEN pin agrees across three files | a switch that exists only in prose |
| the CI gate | paths that look like documentation and are not; failing open | skipping the build on the commit that needed it |
| the badges | a manifest that records nothing is refused; a landing page claiming the wrong count fails | a badge advertising a number nobody proved |

## What cannot be checked here

Anything importing the TEN runtime. `tman` installs it into the image and
nowhere else, so a unit test cannot import those modules at all, and a stub of
the runtime would be a test of the stub. `pyproject.toml` excludes them saying
so, and `descriptor.py` is deliberately free of that dependency **so the rule
§16 rests on is testable**.

The image build and a running graph exercise the rest, and the ledger records
both as what they are.

## The badges cannot lie

`docs/witnesses.json` is written from a real run by `scripts/witnesses.py`, and
`--check` re-runs the suite and fails if the recorded figure has drifted. The
count also appears in prose on the landing page and the README, and it is
**written there by the same script** — a hand-edited number left the page a run
behind every time a test was added, which the guard then reported as drift.

If the manifest and the suite disagree, CI fails rather than publishing the
prettier number.

## Running them

```sh
make test                  # the checks
make witnesses             # record what they witnessed
make witnesses ARGS=--check   # fail if the record has drifted
```

The panel's arithmetic is JavaScript and runs through `node` in the same suite;
without node those checks skip **visibly** rather than pass.
