import { protocolTheme } from "@/lib/protocolTheme";

interface ProtocolDonutProps {
  callsByProtocol: Record<string, number>;
}

export function ProtocolDonut({ callsByProtocol }: ProtocolDonutProps) {
  const entries = Object.entries(callsByProtocol);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-6">
        <div className="flex size-32 items-center justify-center rounded-full border-4 border-dashed border-border text-xs text-muted-foreground">
          Sin datos
        </div>
      </div>
    );
  }

  let cumulative = 0;
  const stops = entries.map(([protocol, count]) => {
    const start = (cumulative / total) * 360;
    cumulative += count;
    const end = (cumulative / total) * 360;
    return `${protocolTheme(protocol).chartColor} ${start}deg ${end}deg`;
  });

  return (
    <div className="flex flex-col items-center gap-4 py-2">
      <div
        className="relative flex size-32 items-center justify-center rounded-full"
        style={{ background: `conic-gradient(${stops.join(", ")})` }}
      >
        <div className="flex size-20 flex-col items-center justify-center rounded-full bg-card text-center shadow-inner">
          <span className="text-lg font-semibold">{total}</span>
          <span className="text-[10px] text-muted-foreground">llamadas</span>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        {entries.map(([protocol, count]) => {
          const theme = protocolTheme(protocol);
          return (
            <div key={protocol} className="flex items-center gap-2 text-xs">
              <span className="size-2 rounded-full" style={{ backgroundColor: theme.chartColor }} />
              <span className="text-muted-foreground">{theme.label}</span>
              <span className="font-medium">
                {count} ({Math.round((count / total) * 100)}%)
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
