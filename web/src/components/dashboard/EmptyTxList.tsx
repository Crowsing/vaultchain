/**
 * Empty transactions list — Phase 1 has no chain context yet, so this
 * is the only state for now. AC-phase1-web-004-01 specifies the
 * exact copy.
 */
export function EmptyTxList(): React.JSX.Element {
  return (
    <section
      data-testid="empty-tx-list"
      className="rounded-lg bg-bg-surface p-6 text-center ring-1 ring-border-default"
    >
      <h3 className="text-base font-semibold text-text-primary">
        Recent activity
      </h3>
      <p className="mt-2 text-sm text-text-secondary">
        No activity yet. Your transactions will appear here.
      </p>
    </section>
  );
}
