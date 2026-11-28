import React, { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Info, Minus } from "lucide-react";
import { CB_V2, METRIC_EXPLANATIONS } from "./adminTheme";

export const MetricInfoTooltip: React.FC<{
  metricKey: string;
  customText?: string;
}> = ({ metricKey, customText }) => {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const def = METRIC_EXPLANATIONS[metricKey];
  if (!def && !customText) return null;

  const isOpen = hovered || pinned;

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => {
        setHovered(false);
        setPinned(false);
      }}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setPinned((v) => !v);
        }}
        aria-label={`Explain ${def?.title || metricKey}`}
        className="rounded-full p-0.5 text-[#9BAFC2] hover:text-[#20C5D8] focus:outline-none"
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {isOpen && (
        <div
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-6 z-40 w-64 rounded-xl border border-[#20C5D8]/35 bg-[#0B1929] p-3 text-left text-[11px] leading-relaxed text-[#F4F8FC] shadow-2xl"
        >
          <div className="font-bold text-[#20C5D8]">{def?.title || metricKey}</div>
          <p className="mt-1 text-[#9BAFC2]">{customText || def?.summary}</p>
          {def?.formula && (
            <div className="mt-1.5 rounded bg-[#153149] px-2 py-1 font-mono text-[10px] text-[#F4F8FC]">
              {def.formula}
            </div>
          )}
        </div>
      )}
    </span>
  );
};

export interface KpiSparkCardProps {
  label: string;
  metricKey: string;
  value: string;
  previousValue?: string | null;
  changePercent?: number | null;
  changeSuffix?: string;
  invertGood?: boolean;
  explanation?: string;
  sparkValues?: number[];
  accentColor?: string;
  onClick?: () => void;
}

export const KpiSparkCard: React.FC<KpiSparkCardProps> = ({
  label,
  metricKey,
  value,
  previousValue,
  changePercent,
  changeSuffix = "%",
  invertGood = false,
  explanation,
  sparkValues = [],
  accentColor = CB_V2.accentCyan,
  onClick,
}) => {
  const hasDelta = changePercent !== null && changePercent !== undefined && Number.isFinite(changePercent);
  const isZero = hasDelta && Number(changePercent) === 0;
  const isUp = hasDelta && Number(changePercent) > 0;
  const isPositiveOutcome = hasDelta ? (invertGood ? !isUp && !isZero : isUp) : true;

  const deltaColor = !hasDelta
    ? "text-[#9BAFC2] bg-[#153149]"
    : isZero
    ? "text-[#9BAFC2] bg-[#153149]"
    : isPositiveOutcome
    ? "text-[#22C58B] bg-[#22C58B]/15"
    : "text-[#F06464] bg-[#F06464]/15";

  // Build clean SVG polyline from actual series values
  let sparkPath = "";
  let sparkArea = "";
  if (sparkValues.length >= 2) {
    const min = Math.min(...sparkValues);
    const max = Math.max(...sparkValues);
    const span = max - min || 1;
    const width = 100;
    const height = 28;
    const pts = sparkValues.map((v, i) => {
      const x = (i / (sparkValues.length - 1)) * width;
      const y = height - 4 - ((v - min) / span) * (height - 8);
      return [x, y];
    });
    sparkPath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    sparkArea = `${sparkPath} L${width},${height} L0,${height} Z`;
  }

  return (
    <div
      onClick={onClick}
      className={`group relative rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4 transition-all ${
        onClick ? "cursor-pointer hover:border-[#20C5D8]/50 hover:bg-[#132b42]" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[#9BAFC2]">{label}</span>
        <MetricInfoTooltip metricKey={metricKey} />
      </div>

      <div className="mt-2 flex items-baseline justify-between gap-2">
        <div className="text-2xl font-black tracking-tight text-[#F4F8FC]">{value}</div>
        {hasDelta ? (
          <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-bold ${deltaColor}`}>
            {isZero ? (
              <Minus className="h-3 w-3" />
            ) : isUp ? (
              <ArrowUpRight className="h-3 w-3" />
            ) : (
              <ArrowDownRight className="h-3 w-3" />
            )}
            {isUp ? "+" : ""}
            {changePercent}
            {changeSuffix}
          </span>
        ) : (
          <span className="rounded-full bg-[#153149] px-2 py-0.5 text-[10px] font-semibold text-[#9BAFC2]">
            No prior baseline
          </span>
        )}
      </div>

      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="text-[11px] text-[#9BAFC2]">
          {previousValue !== undefined && previousValue !== null ? (
            <span>
              Prior: <strong className="text-[#F4F8FC]/90">{previousValue}</strong>
            </span>
          ) : (
            <span>Prior: Data unavailable</span>
          )}
        </div>
        {sparkValues.length >= 2 && (
          <svg viewBox="0 0 100 28" className="h-7 w-24 shrink-0 overflow-visible" aria-hidden="true">
            <path d={sparkArea} fill={accentColor} fillOpacity={0.14} />
            <path d={sparkPath} fill="none" stroke={accentColor} strokeWidth={2} strokeLinecap="round" />
          </svg>
        )}
      </div>

      {explanation && (
        <p className="mt-2 border-t border-[#368BEA]/15 pt-2 text-[11px] leading-snug text-[#9BAFC2]">{explanation}</p>
      )}
    </div>
  );
};

export const V2PanelHeader: React.FC<{
  title: string;
  subtitle: string;
  rightSlot?: React.ReactNode;
}> = ({ title, subtitle, rightSlot }) => (
  <div className="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 className="text-lg font-extrabold tracking-tight text-[#F4F8FC]">{title}</h2>
      <p className="text-xs text-[#9BAFC2]">{subtitle}</p>
    </div>
    {rightSlot && <div className="flex flex-wrap items-center gap-2">{rightSlot}</div>}
  </div>
);

export const V2DataUnavailableBox: React.FC<{
  title: string;
  detail: string;
}> = ({ title, detail }) => (
  <div className="rounded-2xl border border-dashed border-[#368BEA]/30 bg-[#102438]/70 p-6 text-center">
    <div className="text-sm font-bold text-[#F4F8FC]">{title}</div>
    <p className="mt-1 text-xs text-[#9BAFC2]">{detail}</p>
  </div>
);
