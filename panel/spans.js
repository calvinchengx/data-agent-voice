// Turning a stream of graph messages into the five spans that matter.
//
// Pure functions, because the arithmetic is the part worth being sure about
// and a browser is a bad place to find out it was wrong. tests/test_panel.py
// runs these through node.

export const PHASES = ['end of utterance', 'host TTFT', 'first audio', 'answer'];

// A turn begins when the caller stops talking and ends when the last thing
// owed to them has been said. Everything in between is a span.
export function newTurn(id, at) {
  return { id, at, marks: {}, tier: null, kinds: [] };
}

export function mark(turn, name, at) {
  // First write wins: a mark is when something FIRST happened, and a model
  // that streams twenty deltas must not move "first audio" to the last one.
  if (turn.marks[name] === undefined) turn.marks[name] = at;
  return turn;
}

export function spans(turn) {
  const m = turn.marks;
  const between = (a, b) => (m[a] !== undefined && m[b] !== undefined ? m[b] - m[a] : null);
  return {
    'end of utterance': between('speech end', 'transcript final'),
    'host TTFT': between('transcript final', 'model first token'),
    'first audio': between('transcript final', 'audio out'),
    answer: between('dispatched', 'answered'),
  };
}

// p95 by nearest rank. With five turns in a demo the honest report is the
// worst one, and nearest rank gives exactly that rather than interpolating
// toward a number no turn actually took.
export function percentile(values, p = 95) {
  const xs = values.filter((v) => typeof v === 'number' && !Number.isNaN(v)).sort((a, b) => a - b);
  if (!xs.length) return null;
  const rank = Math.ceil((p / 100) * xs.length);
  return xs[Math.min(rank, xs.length) - 1];
}

export function summarise(turns) {
  const out = {};
  for (const phase of PHASES) {
    out[phase] = percentile(turns.map((t) => spans(t)[phase]));
  }
  return out;
}

// Which tier a turn took is not announced: it is which tool the model reached
// for. A turn that dispatched is tier 2; one that called a lookup and answered
// is tier 1; one that used no tool at all is tier 0.
export function tierOf(turn) {
  if (turn.kinds.includes('dispatched')) return 2;
  if (turn.kinds.includes('looked up')) return 1;
  return 0;
}
