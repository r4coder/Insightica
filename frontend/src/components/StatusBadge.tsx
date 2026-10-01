const COLORS: Record<string, string> = {
  completed: "bg-signal/10 text-signal-dark border-signal/30",
  running: "bg-gold/10 text-gold border-gold/30",
  partial: "bg-gold/10 text-gold border-gold/30",
  retry: "bg-gold/10 text-gold border-gold/30",
  skipped: "bg-graphite/10 text-graphite border-graphite/30",
  failed: "bg-alert/10 text-alert border-alert/30",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-xs ${COLORS[status] ?? COLORS.skipped}`}>
      {status}
    </span>
  );
}
