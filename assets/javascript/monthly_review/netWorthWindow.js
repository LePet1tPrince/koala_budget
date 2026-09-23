/**
 * The slice of the net worth section matching the selected baseline: the
 * baseline's months plus the month under review. The server sends the whole
 * span (back to the team's first activity), so switching baseline never needs
 * a new request. With no baseline (a team's first month) only this month shows.
 */
export function netWorthWindow(netWorth, baseline, month) {
  const wanted = new Set([...(baseline ? baseline.keys : []), month]);
  const indexes = netWorth.series.map((point, i) => (wanted.has(point.key) ? i : -1)).filter((i) => i >= 0);
  const pick = (values) => indexes.map((i) => values[i]);
  return {
    series: pick(netWorth.series),
    stack: netWorth.stack.map((s) => ({ ...s, values: pick(s.values) })),
  };
}

/** An account row's change over the selected baseline, or null when there is none. */
export function accountChange(row, baseline) {
  if (!baseline || !row.changes) return null;
  const change = row.changes[baseline.id];
  return change === undefined ? null : change;
}
