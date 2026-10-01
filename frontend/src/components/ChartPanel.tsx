import { useEffect, useRef } from "react";
import type { ChartResult } from "../types";

/** Renders a server-built Plotly figure (data+layout only - no code from the LLM runs on the client). */
export default function ChartPanel({ chart }: { chart: ChartResult }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    import("plotly.js-dist-min").then((Plotly) => {
      if (disposed || !ref.current) return;
      Plotly.default.newPlot(ref.current, chart.figure.data as never, {
        ...chart.figure.layout,
        font: { family: "Inter, system-ui, sans-serif", color: "#161B18", size: 12 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        colorway: ["#1F6B62", "#B08A2E", "#4B5157", "#2C8C80", "#B23B3B"],
      }, { responsive: true, displaylogo: false });
    });
    return () => {
      disposed = true;
    };
  }, [chart]);

  return (
    <div className="panel p-4">
      <h4 className="mb-2 font-display text-sm font-semibold">{chart.title}</h4>
      <div ref={ref} className="h-80 w-full" />
    </div>
  );
}
