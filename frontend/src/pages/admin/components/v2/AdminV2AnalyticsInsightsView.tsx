import React, { Suspense, lazy, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowUpRight,
  Clock,
  Flame,
  Lightbulb,
  ShoppingBag,
  Sparkles,
  Utensils,
} from "lucide-react";
import { CB_V2, V2_CHART_AXIS_TICK, V2_PIE_COLORS, V2_TOOLTIP_STYLE, formatCompactInr, formatInr } from "./adminTheme";
import { MetricInfoTooltip, V2PanelHeader } from "./AdminV2Widgets";

const ForecastingAssistantTab = lazy(() =>
  import("../ForecastingAssistantTab").then((m) => ({ default: m.ForecastingAssistantTab }))
);

interface AdminV2AnalyticsInsightsViewProps {
  report: any;
  activeCanteenId: string;
  onJumpToOrderDrilldown: () => void;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HEATMAP_HOURS = Array.from({ length: 16 }, (_, i) => i + 7);
const LINE_COLORS = ["#20C5D8", "#368BEA", "#22C58B", "#F5B942", "#8B5CF6"];

export const AdminV2AnalyticsInsightsView: React.FC<AdminV2AnalyticsInsightsViewProps> = ({
  report,
  activeCanteenId,
  onJumpToOrderDrilldown,
}) => {
  const [subTab, setSubTab] = useState<"intelligence" | "orders_bi" | "food_bi" | "ai_assistant">("intelligence");
  const [domainFilter, setDomainFilter] = useState<string>("all");

  const sales = report?.sales || {};
  const ops = report?.operations || {};
  const insights: any[] = report?.business_insights || [];

  const filteredInsights =
    domainFilter === "all"
      ? insights
      : insights.filter((i) => (i.bi_domain || i.category || "").toLowerCase() === domainFilter);

  const nonEmptyHours = (sales.hourly_series || []).filter(
    (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
  );
  const peakHours = ops.peak_hours || [];
  const busiestHour = peakHours[0];
  const busiestEndNum = busiestHour ? (Number(busiestHour.hour.slice(0, 2)) + 2) % 24 : null;

  const heatmapCells: any[] = sales.hourly_heatmap || [];
  const heatmapMax = Math.max(1, ...heatmapCells.map((c) => Number(c.orders || 0)));
  const heatmapLookup = new Map<string, any>();
  for (const c of heatmapCells) heatmapLookup.set(`${c.weekday_index}:${c.hour}`, c);

  const top10Items = (sales.top_items || []).slice(0, 10).map((t: any) => ({
    ...t,
    short_name: t.item_name.length > 18 ? `${t.item_name.slice(0, 17)}…` : t.item_name,
  }));
  const profitableItems = (sales.top_items || []).filter((t: any) => t.profitability_available);
  const demandKeys: string[] = sales.product_demand_trend_keys || [];
  const demandSeries: any[] = sales.product_demand_trends || [];

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Analytics & CollegeBites Intelligence"
        subtitle="Plain-English database insights, order rush patterns, menu demand ranking, and AI assistant."
        rightSlot={
          <div className="flex flex-wrap items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
            {[
              { k: "intelligence", l: "CollegeBites Intelligence" },
              { k: "orders_bi", l: "Order Analytics" },
              { k: "food_bi", l: "Food Performance" },
              { k: "ai_assistant", l: "AI Assistant & Forecast" },
            ].map((t) => (
              <button
                key={t.k}
                type="button"
                onClick={() => setSubTab(t.k as any)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                  subTab === t.k ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                }`}
              >
                {t.l}
              </button>
            ))}
          </div>
        }
      />

      {subTab === "ai_assistant" && (
        <Suspense
          fallback={
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
              Loading AI Forecasting &amp; Operations Assistant...
            </div>
          }
        >
          <ForecastingAssistantTab activeCanteenId={activeCanteenId} canTrainForecast canViewForecast canViewAudit />
        </Suspense>
      )}

      {subTab === "intelligence" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#20C5D8]/25 bg-[#102438] p-4">
            <div className="flex items-center gap-2.5">
              <Lightbulb className="h-5 w-5 text-[#20C5D8]" />
              <div>
                <div className="text-sm font-extrabold text-[#F4F8FC]">
                  Automated Business Explanations (No SQL or Analytics Required)
                </div>
                <div className="text-xs text-[#9BAFC2]">
                  Deterministic rules inspect your real database numbers and explain what changed, why it matters, and what action to take.
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["all", "revenue", "orders", "food", "operational", "payment"].map((dom) => (
                <button
                  key={dom}
                  type="button"
                  onClick={() => setDomainFilter(dom)}
                  className={`rounded-lg border px-2.5 py-1 text-[11px] font-bold capitalize transition ${
                    domainFilter === dom
                      ? "border-[#20C5D8] bg-[#20C5D8]/20 text-[#20C5D8]"
                      : "border-[#368BEA]/25 bg-[#153149] text-[#9BAFC2] hover:text-[#F4F8FC]"
                  }`}
                >
                  {dom}
                </button>
              ))}
            </div>
          </div>

          {filteredInsights.length === 0 ? (
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
              No triggered rules for this category and date range — operations look steady.
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {filteredInsights.map((ins: any) => {
                const urgency = (ins.urgency || ins.severity || "info").toLowerCase();
                const urgencyBadge =
                  urgency === "critical"
                    ? "bg-[#F06464]/15 text-[#F06464] border-[#F06464]/40"
                    : urgency === "high" || urgency === "warning"
                    ? "bg-[#F5B942]/15 text-[#F5B942] border-[#F5B942]/40"
                    : urgency === "positive"
                    ? "bg-[#22C58B]/15 text-[#22C58B] border-[#22C58B]/40"
                    : "bg-[#20C5D8]/15 text-[#20C5D8] border-[#20C5D8]/40";

                return (
                  <div
                    key={ins.id}
                    className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 flex flex-col justify-between gap-4"
                  >
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="rounded-full bg-[#153149] px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#20C5D8]">
                            {ins.bi_domain || ins.category} Insight
                          </span>
                          <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase ${urgencyBadge}`}>
                            Urgency: {urgency}
                          </span>
                        </div>
                        <span className="font-mono text-xs font-extrabold text-[#F4F8FC]">{ins.metric_label}</span>
                      </div>

                      <div>
                        <div className="text-[11px] font-bold uppercase tracking-wider text-[#9BAFC2]">1. What happened</div>
                        <div className="mt-0.5 text-sm font-extrabold text-[#F4F8FC]">
                          {ins.what_happened || ins.title}
                        </div>
                      </div>

                      <div className="grid gap-2.5 sm:grid-cols-2 text-xs">
                        <div className="rounded-xl bg-[#153149]/80 p-3">
                          <div className="text-[10px] font-bold uppercase text-[#9BAFC2]">2. Why it matters</div>
                          <p className="mt-1 text-[#F4F8FC]/90 leading-relaxed">
                            {ins.why_it_matters || "Impacts canteen throughput and revenue efficiency."}
                          </p>
                        </div>
                        <div className="rounded-xl bg-[#153149]/80 p-3 border border-[#20C5D8]/20">
                          <div className="text-[10px] font-bold uppercase text-[#20C5D8]">3. Recommended Action</div>
                          <p className="mt-1 text-[#F4F8FC]/90 leading-relaxed">
                            {ins.recommended_action || ins.detail}
                          </p>
                        </div>
                      </div>

                      <div className="rounded-xl bg-[#0B1929] px-3 py-2 text-[11px] text-[#9BAFC2]">
                        <strong className="text-[#F4F8FC]">Supporting Data:</strong> {ins.supporting_data || ins.detail}
                      </div>
                    </div>

                    <div className="flex items-center justify-between border-t border-[#368BEA]/15 pt-2.5 text-xs">
                      <span className="text-[10px] text-[#9BAFC2]">Classification: Real DB Business Rule</span>
                      <button
                        type="button"
                        onClick={onJumpToOrderDrilldown}
                        className="inline-flex items-center gap-1 font-bold text-[#20C5D8] hover:underline"
                      >
                        Inspect Order History <ArrowUpRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {subTab === "orders_bi" && (
        <div className="space-y-5">
          {/* Plain-language rush guidance ONLY when supported by actual history */}
          {busiestHour ? (
            <div className="rounded-2xl border border-[#20C5D8]/30 bg-[#102438] p-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Clock className="h-5 w-5 text-[#20C5D8] shrink-0" />
                <div className="text-xs text-[#F4F8FC]">
                  Your busiest ordering period is between{" "}
                  <strong className="text-[#20C5D8]">
                    {busiestHour.hour} and {String(busiestEndNum).padStart(2, "0")}:00
                  </strong>{" "}
                  ({busiestHour.orders} confirmed orders worth {formatInr(busiestHour.revenue)}). Consider preparing additional food stock ahead of this rush window.
                </div>
              </div>
              <MetricInfoTooltip metricKey="completion_rate" />
            </div>
          ) : (
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4 text-xs text-[#9BAFC2]">
              Peak ordering window: Data unavailable (no confirmed orders in selected range).
            </div>
          )}

          {/* Status & Timing Strip */}
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6 text-xs">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-3.5">
              <div className="text-[#9BAFC2]">Total Confirmed</div>
              <div className="mt-1 text-xl font-black text-[#F4F8FC]">{sales.total_orders ?? 0}</div>
            </div>
            <div className="rounded-2xl border border-[#22C58B]/25 bg-[#102438] p-3.5">
              <div className="text-[#22C58B]">Completed</div>
              <div className="mt-1 text-xl font-black text-[#22C58B]">
                {ops.completed_orders ?? 0} ({ops.completion_rate_percent ?? 0}%)
              </div>
            </div>
            <div className="rounded-2xl border border-[#F5B942]/25 bg-[#102438] p-3.5">
              <div className="text-[#F5B942]">Pending / Processing</div>
              <div className="mt-1 text-xl font-black text-[#F5B942]">
                {ops.queued_pending_orders ?? 0} / {ops.processing_orders ?? 0}
              </div>
            </div>
            <div className="rounded-2xl border border-[#F06464]/25 bg-[#102438] p-3.5">
              <div className="text-[#F06464]">Cancelled</div>
              <div className="mt-1 text-xl font-black text-[#F06464]">
                {ops.cancelled_orders ?? 0} ({ops.cancellation_rate_percent ?? 0}%)
              </div>
            </div>
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-3.5">
              <div className="text-[#9BAFC2]">Avg Prep Time</div>
              <div className="mt-1 text-xl font-black text-[#20C5D8]">
                {ops.has_prep_timestamps ? `${ops.avg_prep_minutes} min` : "Data unavailable"}
              </div>
            </div>
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-3.5">
              <div className="text-[#9BAFC2]">Avg Completion Time</div>
              <div className="mt-1 text-xl font-black text-[#F4F8FC]">
                {ops.has_completion_timestamps ? `${ops.avg_completion_minutes} min` : "Data unavailable"}
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center gap-2 mb-3">
                <ShoppingBag className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Daily Order Trends (Paid vs Completed vs Cancelled)</h3>
              </div>
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={sales.daily_series || []}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                    <Area isAnimationActive={false} type="monotone" dataKey="orders" name="Paid Orders" stroke="#20C5D8" fill="#20C5D8" fillOpacity={0.2} />
                    <Area isAnimationActive={false} type="monotone" dataKey="completed_orders" name="Completed" stroke="#22C58B" fill="#22C58B" fillOpacity={0.18} />
                    <Area isAnimationActive={false} type="monotone" dataKey="cancelled_orders" name="Cancelled" stroke="#F06464" fill="#F06464" fillOpacity={0.14} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <h3 className="text-sm font-extrabold text-[#F4F8FC] mb-3">Interactive Hourly Order Distribution</h3>
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={nonEmptyHours}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="hour" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                    <Bar isAnimationActive={false} dataKey="orders" name="Paid Orders" fill="#20C5D8" radius={[4, 4, 0, 0]} />
                    <Bar isAnimationActive={false} dataKey="completed_orders" name="Completed" fill="#22C58B" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Hourly Heatmap */}
          <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-3">
            <h3 className="text-sm font-extrabold text-[#F4F8FC]">Campus Rush Heatmap (Day × Hour)</h3>
            <div className="overflow-x-auto">
              <div className="min-w-[560px] space-y-1">
                <div className="grid grid-cols-[44px_repeat(16,minmax(0,1fr))] gap-1 text-[10px] font-mono text-center text-[#9BAFC2]">
                  <div />
                  {HEATMAP_HOURS.map((hr) => (
                    <div key={hr}>{String(hr).padStart(2, "0")}h</div>
                  ))}
                </div>
                {WEEKDAY_LABELS.map((wdName, wdIdx) => (
                  <div key={wdName} className="grid grid-cols-[44px_repeat(16,minmax(0,1fr))] gap-1 items-center">
                    <div className="text-[11px] font-bold text-[#9BAFC2]">{wdName}</div>
                    {HEATMAP_HOURS.map((hr) => {
                      const cell = heatmapLookup.get(`${wdIdx}:${hr}`);
                      const cnt = Number(cell?.orders || 0);
                      const ratio = cnt / heatmapMax;
                      const cls =
                        cnt === 0
                          ? "bg-[#153149]/50 text-[#9BAFC2]/30"
                          : ratio >= 0.75
                          ? "bg-[#20C5D8] text-[#071321] font-black"
                          : ratio >= 0.45
                          ? "bg-[#368BEA] text-[#F4F8FC] font-bold"
                          : "bg-[#22C58B]/40 text-[#F4F8FC] font-semibold";
                      return (
                        <div
                          key={hr}
                          title={`${wdName} ${String(hr).padStart(2, "0")}:00 — ${cnt} orders (${formatInr(cell?.revenue || 0)})`}
                          className={`h-6 rounded flex items-center justify-center text-[10px] ${cls}`}
                        >
                          {cnt > 0 ? cnt : ""}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {subTab === "food_bi" && (
        <div className="space-y-5">
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Top 10 Ranked Items */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Flame className="h-4 w-4 text-[#F5B942]" />
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">Top 10 Food Items Ranking</h3>
                </div>
                <span className="text-[11px] text-[#9BAFC2]">Prepare more of highest-velocity dishes</span>
              </div>
              {top10Items.length === 0 ? (
                <div className="h-64 flex items-center justify-center text-xs text-[#9BAFC2]">
                  No dish sales recorded in selected range.
                </div>
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={top10Items} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                      <XAxis type="number" tick={V2_CHART_AXIS_TICK} />
                      <YAxis type="category" dataKey="short_name" width={125} tick={V2_CHART_AXIS_TICK} />
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                      <Bar isAnimationActive={false} dataKey="revenue" name="Revenue (₹)" fill="#20C5D8" radius={[0, 4, 4, 0]} />
                      <Bar isAnimationActive={false} dataKey="quantity_sold" name="Qty Sold" fill="#368BEA" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Popularity Trends */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Top 5 Dish Popularity Trends (Daily Qty)</h3>
              </div>
              {demandKeys.length === 0 || demandSeries.length === 0 ? (
                <div className="h-72 flex items-center justify-center text-xs text-[#9BAFC2]">
                  Daily demand trend unavailable for this window.
                </div>
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={demandSeries}>
                      <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={V2_CHART_AXIS_TICK} />
                      <YAxis tick={V2_CHART_AXIS_TICK} />
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 10, color: "#9BAFC2" }} />
                      {demandKeys.map((name, idx) => (
                        <Line
                          key={name}
                          isAnimationActive={false}
                          type="monotone"
                          dataKey={name}
                          stroke={LINE_COLORS[idx % LINE_COLORS.length]}
                          strokeWidth={2}
                          dot={false}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Category Performance Donut */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center gap-2 mb-2">
                <Utensils className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Category Revenue Mix</h3>
              </div>
              {(sales.category_sales || []).length === 0 ? (
                <div className="h-52 flex items-center justify-center text-xs text-[#9BAFC2]">No category sales in range.</div>
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={sales.category_sales}
                        dataKey="revenue"
                        nameKey="category"
                        innerRadius={44}
                        outerRadius={72}
                        paddingAngle={2}
                      >
                        {(sales.category_sales || []).map((_e: any, idx: number) => (
                          <Cell key={`fcat-${idx}`} fill={V2_PIE_COLORS[idx % V2_PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} formatter={(v: any) => formatInr(v)} />
                      <Legend wrapperStyle={{ fontSize: 10, color: "#9BAFC2" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Most Profitable Items (strictly real cost data only) */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-2.5">
              <h3 className="text-sm font-extrabold text-[#F4F8FC]">Most Profitable Items</h3>
              {profitableItems.length === 0 ? (
                <div className="rounded-xl border border-dashed border-[#368BEA]/30 bg-[#153149]/60 p-4 text-xs text-[#9BAFC2]">
                  <strong className="text-[#F4F8FC]">Data unavailable:</strong> Verified recipe ingredient costs are not yet linked to top items. Add recipe ingredient unit costs in Inventory to track per-dish gross profit honestly.
                </div>
              ) : (
                <div className="space-y-2 text-xs">
                  {profitableItems
                    .slice()
                    .sort((a: any, b: any) => (b.estimated_profit || 0) - (a.estimated_profit || 0))
                    .slice(0, 6)
                    .map((p: any) => (
                      <div key={p.item_name} className="flex items-center justify-between rounded-xl bg-[#153149] px-3 py-2">
                        <span className="font-semibold text-[#F4F8FC]">{p.item_name}</span>
                        <span className="font-bold text-[#22C58B]">
                          {formatInr(p.estimated_profit)} ({p.estimated_margin_percent}%)
                        </span>
                      </div>
                    ))}
                </div>
              )}

              <div className="pt-2">
                <h4 className="text-xs font-bold text-[#9BAFC2] mb-1.5">Frequently Ordered Together</h4>
                {(sales.frequent_combinations || []).length === 0 ? (
                  <div className="text-[11px] text-[#9BAFC2]">Not enough multi-item baskets in selected range.</div>
                ) : (
                  <div className="space-y-1.5 text-xs">
                    {(sales.frequent_combinations || []).slice(0, 4).map((c: any) => (
                      <div key={c.pair_label} className="flex items-center justify-between rounded-lg bg-[#0B1929] px-2.5 py-1.5">
                        <span className="text-[#F4F8FC] truncate pr-2">{c.pair_label}</span>
                        <span className="font-bold text-[#20C5D8] shrink-0">{c.co_order_count} orders</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Lowest Selling Items */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-2.5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Lowest-Selling Menu Items</h3>
                <span className="text-[10px] text-[#F5B942]">Observe over 30d before changes</span>
              </div>
              {(sales.least_ordered_items || []).length === 0 ? (
                <div className="py-8 text-center text-xs text-[#9BAFC2]">No active menu items found.</div>
              ) : (
                <div className="space-y-1.5 text-xs">
                  {(sales.least_ordered_items || []).slice(0, 7).map((li: any) => (
                    <div
                      key={li.food_item_id}
                      className="flex items-center justify-between rounded-xl bg-[#153149]/80 px-3 py-2"
                    >
                      <div className="truncate pr-2">
                        <div className="font-semibold text-[#F4F8FC] truncate">{li.item_name}</div>
                        <div className="text-[10px] text-[#9BAFC2]">{li.category_name}</div>
                      </div>
                      <span className="shrink-0 font-bold text-[#9BAFC2]">
                        {li.quantity_sold} sold · {formatCompactInr(li.revenue)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
