/** Tiny dependency-free charts. Values are always labelled in text too, so color isn't the only cue. */

export function BarChart({
  data,
  height = 120,
  ariaLabel,
}: {
  data: { label: string; value: number }[];
  height?: number;
  ariaLabel: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div role="img" aria-label={ariaLabel} className="flex items-end gap-1.5" style={{ height }}>
      {data.map((d) => (
        <div key={d.label} className="group flex h-full flex-1 flex-col justify-end gap-1" title={`${d.label}: ${d.value}`}>
          <div
            className="min-h-px w-full rounded-t-sm bg-primary/80 transition-colors group-hover:bg-primary"
            style={{ height: `${(d.value / max) * 100}%` }}
          />
          <span className="truncate text-center font-mono text-[10px] text-muted-foreground">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

export function SplitBars({ rows, total }: { rows: { label: string; value: number; color: string }[]; total: number }) {
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.label} className="space-y-1">
          <div className="flex justify-between text-sm">
            <span>{row.label}</span>
            <span className="font-mono text-xs text-muted-foreground">
              {row.value} · {total ? Math.round((row.value / total) * 100) : 0}%
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full" style={{ width: `${total ? (row.value / total) * 100 : 0}%`, background: row.color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
