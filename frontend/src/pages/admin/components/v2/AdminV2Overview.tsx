import React, { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowUpRight,
  Clock,
  Flame,
  Layers,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import {
  type AdminSectionId,
  CB_V2,
  V2_CHART_AXIS_TICK,
  V2_PIE_COLORS,
  V2_TOOLTIP_STYLE,
  formatCompactInr,
  formatInr,
  formatPresetLabel,
} from "./adminTheme";
import { KpiSparkCard, MetricInfoTooltip, V2DataUnavailableBox } from "./AdminV2Widgets";

interface AdminV2OverviewProps {
  report: any;
  preset: string;
  canteenName: string;
  onNavigateSection: (sec: AdminSectionId) => void;
  onSelectFoodForDrilldown?: (foodId: string) => void;
}

export const AdminV2Overview: React.FC<AdminV2OverviewProps> = ({
  report,
  preset,
  canteenName,
  onNavigateSection,
}) => {
  const [trendMode, setTrendMode] = useState<"daily" | "weekly" | "monthly" | "hourly">("daily");

  const sales = report?.sales || {};
  const ops = report?.operations || {};
  const cust = report?.customers || {};
  const pay = report?.payment_stats || {};
  const fin = report?.financial_analytics || {};
  const comp = report?.period_comparison || null;
  const todaySum = report?.today_summary || {};
  const insights: any[] = report?.business_insights || [];

  const dailySeries: any[] = sales.daily_series || [];
  const activeSeries =
    trendMode === "weekly"
      ? sales.weekly_series || []
      : trendMode === "monthly"
      ? sales.monthly_series || []
      : trendMode === "hourly"
      ? (sales.hourly_series || []).filter(
          (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
        )
      : dailySeries;
  const xKey = trendMode === "weekly" ? "week" : trendMode === "monthly" ? "month" : trendMode === "hourly" ? "hour" : "date";

  const sparkRev = dailySeries.slice(-14).map((d) => Number(d.revenue || 0));
  const sparkOrders = dailySeries.slice(-14).map((d) => Number(d.orders || 0));
  const sparkAov = dailySeries.slice(-14).map((d) => Number(d.aov || 0));
  const sparkCompleted = dailySeries.slice(-14).map((d) => Number(d.completed_orders || 0));
  const sparkCancelled = dailySeries.slice(-14).map((d) => Number(d.cancelled_orders || 0));

  const periodLabel = formatPresetLabel(preset, report?.range?.start_date, report?.range?.end_date);
  const currentRevNum = Number(fin.verified_net_revenue ?? sales.net_sales ?? 0);
  const peakHours = ops.peak_hours || [];
  const topHour = peakHours[0];
  const nonEmptyHours = (sales.hourly_series || []).filter(
    (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
  );
  const topItems = (sales.top_items || []).slice(0, 6);

  const todayDisplay = new Date().toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const revDelta = comp?.revenue_change_percent;
  const revExplanation =
    revDelta !== null && revDelta !== undefined
      ? `Net revenue ${revDelta >= 0 ? "increased" : "decreased"} by ${Math.abs(revDelta)}% compared with the previous period (${comp.previous_range?.start_date} → ${comp.previous_range?.end_date}).`
      : `Verified net collections for ${periodLabel} (${canteenName}).`;

  const ordersDelta = comp?.orders_change_percent;
  const ordersExplanation =
    ordersDelta !== null && ordersDelta !== undefined
      ? `Confirmed orders ${ordersDelta >= 0 ? "grew" : "dropped"} by ${Math.abs(ordersDelta)}% vs ${comp.previous_orders} orders prior.`
      : `${sales.total_created_orders ?? sales.total_orders ?? 0} total orders created (including unpaid/cancelled).`;

  return (
    <div className="space-y-6">
      {/* Welcome Hero Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#20C5D8]/20 bg-gradient-to-r from-[#0B1929] via-[#102438] to-[#153149] p-5">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-black tracking-tight text-[#F4F8FC]">Good Morning, Admin</h1>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#22C58B]/35 bg-[#22C58B]/15 px-2.5 py-0.5 text-[11px] font-bold text-[#22C58B]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#22C58B] animate-pulse" />
              Verified Real-Time Ledger
            </span>
          </div>
          <p className="mt-1 text-sm text-[#9BAFC2]">
            Here is your CollegeBites business performance overview.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-[#9BAFC2]">
            <span className="rounded-lg border border-[#368BEA]/25 bg-[#071321]/70 px-2.5 py-1 font-medium text-[#F4F8FC]">
              {todayDisplay}
            </span>
            <span className="rounded-lg border border-[#20C5D8]/25 bg-[#20C5D8]/10 px-2.5 py-1 font-semibold text-[#20C5D8]">
              Selected Period: {report?.range?.start_date} → {report?.range?.end_date} ({periodLabel})
            </span>
            <span className="rounded-lg border border-[#368BEA]/25 bg-[#071321]/70 px-2.5 py-1">
              Scope: <strong className="text-[#F4F8FC]">{canteenName}</strong>
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-[#368BEA]/20 bg-[#071321]/75 px-3.5 py-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-[#9BAFC2]">Today Revenue</div>
            <div className="mt-0.5 text-lg font-black text-[#20C5D8]">{formatInr(todaySum.revenue_today ?? 0)}</div>
            <div className="text-[10px] text-[#9BAFC2]">{todaySum.total_orders_today ?? 0} paid orders today</div>
          </div>
          <div className="rounded-xl border border-[#368BEA]/20 bg-[#071321]/75 px-3.5 py-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-[#9BAFC2]">Live Queue Now</div>
            <div className="mt-0.5 text-lg font-black text-[#F5B942]">{todaySum.active_pending_orders ?? 0} Active</div>
            <div className="text-[10px] text-[#9BAFC2]">Kitchen Load: {ops.kitchen_workload_percent ?? 0}%</div>
          </div>
          <div className="col-span-2 sm:col-span-1 rounded-xl border border-[#368BEA]/20 bg-[#071321]/75 px-3.5 py-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-[#9BAFC2]">Payment Reliability</div>
            <div className="mt-0.5 text-lg font-black text-[#22C58B]">{pay.success_rate_percent ?? 0}%</div>
            <div className="text-[10px] text-[#9BAFC2]">
              {pay.confirmed_count ?? 0} ok • {pay.failed_count ?? 0} failed
            </div>
          </div>
        </div>
      </div>

      {report?.empty && (
        <V2DataUnavailableBox
          title="No confirmed orders found for this period"
          detail={report.empty_message || "Switch the date range preset above or clear canteen filters to inspect historical orders."}
        />
      )}

      {/* 8 Executive KPI Cards */}
      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <KpiSparkCard
          label="1. Total Revenue"
          metricKey="total_revenue"
          value={formatInr(currentRevNum)}
          previousValue={comp ? formatInr(comp.previous_net_revenue) : null}
          changePercent={revDelta}
          sparkValues={sparkRev}
          accentColor={CB_V2.accentCyan}
          explanation={revExplanation}
          onClick={() => onNavigateSection("finance")}
        />
        <KpiSparkCard
          label="2. Total Orders"
          metricKey="total_orders"
          value={String(sales.total_orders ?? 0)}
          previousValue={comp ? String(comp.previous_orders ?? 0) : null}
          changePercent={ordersDelta}
          sparkValues={sparkOrders}
          accentColor={CB_V2.accentBlue}
          explanation={ordersExplanation}
          onClick={() => onNavigateSection("order_history")}
        />
        <KpiSparkCard
          label="3. Completed Orders"
          metricKey="completed_orders"
          value={String(ops.completed_orders ?? 0)}
          previousValue={comp ? String(comp.previous_completed_orders ?? 0) : null}
          changePercent={comp?.completed_change_percent}
          sparkValues={sparkCompleted}
          accentColor={CB_V2.success}
          explanation="Orders successfully cooked, packed, and handed over."
          onClick={() => onNavigateSection("order_history")}
        />
        <KpiSparkCard
          label="4. Pending Orders"
          metricKey="pending_orders"
          value={String(ops.pending_orders ?? 0)}
          previousValue={comp ? String(comp.previous_pending_orders ?? 0) : null}
          changePercent={comp?.pending_change_percent}
          invertGood
          accentColor={CB_V2.warning}
          explanation={`${ops.queued_pending_orders ?? 0} queued • ${ops.processing_orders ?? 0} preparing • ${ops.ready_orders ?? 0} ready`}
          onClick={() => onNavigateSection("live_orders")}
        />
        <KpiSparkCard
          label="5. Average Order Value"
          metricKey="aov"
          value={formatInr(sales.average_order_value ?? 0)}
          previousValue={comp ? formatInr(comp.previous_aov) : null}
          changePercent={comp?.aov_change_percent}
          sparkValues={sparkAov}
          accentColor={CB_V2.accentCyan}
          explanation="Average spend per confirmed paid order."
          onClick={() => onNavigateSection("finance")}
        />
        <KpiSparkCard
          label="6. Active Customers"
          metricKey="active_customers"
          value={String(cust.active_ordering_customers ?? 0)}
          previousValue={comp ? String(comp.previous_active_customers ?? 0) : null}
          changePercent={comp?.active_customers_change_percent}
          accentColor={CB_V2.accentBlue}
          explanation={`${cust.returning_customers ?? 0} repeat buyers (${cust.repeat_order_rate_percent ?? 0}% repeat rate).`}
          onClick={() => onNavigateSection("customers")}
        />
        <KpiSparkCard
          label="7. Completion Rate"
          metricKey="completion_rate"
          value={`${ops.completion_rate_percent ?? 0}%`}
          previousValue={comp ? `${comp.previous_completion_rate ?? 0}%` : null}
          changePercent={comp?.completion_rate_diff_points}
          changeSuffix=" pts"
          accentColor={CB_V2.success}
          explanation="Share of paid orders handed over smoothly."
          onClick={() => onNavigateSection("analytics_insights")}
        />
        <KpiSparkCard
          label="8. Cancellation Rate"
          metricKey="cancellation_rate"
          value={`${ops.cancellation_rate_percent ?? 0}%`}
          previousValue={comp ? `${comp.previous_cancellation_rate ?? 0}%` : null}
          changePercent={comp?.cancellation_rate_diff_points}
          changeSuffix=" pts"
          invertGood
          sparkValues={sparkCancelled}
          accentColor={CB_V2.danger}
          explanation={`${ops.cancelled_orders ?? 0} cancelled out of ${sales.total_created_orders ?? 0} created orders.`}
          onClick={() => onNavigateSection("order_history")}
        />
      </div>

      {/* Primary Charts Row (Inspired by Admin Dashboard V2 Reference Video) */}
      <div className="grid gap-4 lg:grid-cols-12">
        {/* Daily/Weekly/Monthly Revenue & Orders Composed Chart */}
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-8">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
            <div>
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Revenue &amp; Order Flow</h3>
                <MetricInfoTooltip metricKey="total_revenue" />
              </div>
              <p className="text-[11px] text-[#9BAFC2] mt-0.5">
                Compare net verified collections against confirmed order volume across time.
              </p>
            </div>
            <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
              {(["hourly", "daily", "weekly", "monthly"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setTrendMode(mode)}
                  className={`rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                    trendMode === mode
                      ? "bg-[#20C5D8] text-[#071321]"
                      : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                  }`}
                >
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={activeSeries}>
                <defs>
                  <linearGradient id="cbRevArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#20C5D8" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#20C5D8" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                <XAxis dataKey={xKey} tick={V2_CHART_AXIS_TICK} />
                <YAxis yAxisId="rev" tick={V2_CHART_AXIS_TICK} />
                <YAxis yAxisId="ord" orientation="right" tick={V2_CHART_AXIS_TICK} />
                <Tooltip
                  contentStyle={V2_TOOLTIP_STYLE}
                  formatter={(v: any, name: any) =>
                    String(name).includes("Revenue") ? formatInr(v) : v
                  }
                />
                <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                <Area
                  isAnimationActive={false}
                  yAxisId="rev"
                  type="monotone"
                  dataKey="revenue"
                  name="Net Revenue (₹)"
                  stroke="#20C5D8"
                  strokeWidth={2.5}
                  fill="url(#cbRevArea)"
                />
                <Bar
                  isAnimationActive={false}
                  yAxisId="ord"
                  dataKey="orders"
                  name="Paid Orders"
                  fill="#368BEA"
                  fillOpacity={0.75}
                  radius={[4, 4, 0, 0]}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Payment Method Split & Live Collection Health */}
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Payment Channels</h3>
              </div>
              <button
                type="button"
                onClick={() => onNavigateSection("payments")}
                className="inline-flex items-center gap-1 text-[11px] font-bold text-[#20C5D8] hover:underline"
              >
                Ledger <ArrowUpRight className="h-3 w-3" />
              </button>
            </div>
            <p className="text-[11px] text-[#9BAFC2] mt-0.5">
              Distribution of confirmed Razorpay &amp; POS collections.
            </p>
          </div>

          {(sales.payment_breakdown || []).length === 0 ? (
            <div className="flex h-48 items-center justify-center text-xs text-[#9BAFC2]">
              Data unavailable (no confirmed payments in range)
            </div>
          ) : (
            <div className="h-48 my-2">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    isAnimationActive={false}
                    data={sales.payment_breakdown}
                    dataKey="amount"
                    nameKey="method"
                    innerRadius={44}
                    outerRadius={70}
                    paddingAngle={3}
                  >
                    {(sales.payment_breakdown || []).map((_e: any, i: number) => (
                      <Cell key={`ov-pay-${i}`} fill={V2_PIE_COLORS[i % V2_PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={V2_TOOLTIP_STYLE} formatter={(v: any) => formatInr(v)} />
                  <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 border-t border-[#368BEA]/15 pt-3 text-xs">
            <div className="rounded-xl bg-[#153149] p-2.5">
              <div className="text-[10px] text-[#9BAFC2]">Collected Money</div>
              <div className="font-bold text-[#22C58B]">{formatInr(fin.collected_payments ?? 0)}</div>
            </div>
            <div className="rounded-xl bg-[#153149] p-2.5">
              <div className="text-[10px] text-[#9BAFC2]">Failed Attempts</div>
              <div className="font-bold text-[#F06464]">{pay.failed_count ?? 0} ({formatCompactInr(pay.failed_amount ?? 0)})</div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Operational Row: Hourly Activity, Top Foods & Intelligence Alerts */}
      <div className="grid gap-4 lg:grid-cols-12">
        {/* Hourly Activity */}
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-[#20C5D8]" />
              <h3 className="text-sm font-extrabold text-[#F4F8FC]">Hourly Activity</h3>
            </div>
            {topHour && (
              <span className="rounded-full bg-[#20C5D8]/15 px-2 py-0.5 text-[10px] font-bold text-[#20C5D8]">
                Peak: {topHour.hour}
              </span>
            )}
          </div>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={nonEmptyHours}>
                <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                <XAxis dataKey="hour" tick={{ ...V2_CHART_AXIS_TICK, fontSize: 9 }} />
                <YAxis tick={V2_CHART_AXIS_TICK} />
                <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                <Bar isAnimationActive={false} dataKey="orders" name="Orders" fill="#20C5D8" radius={[3, 3, 0, 0]} />
                <Bar isAnimationActive={false} dataKey="completed_orders" name="Completed" fill="#22C58B" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="rounded-xl bg-[#153149] p-3 text-[11px] text-[#9BAFC2]">
            {topHour ? (
              <>
                Busiest traffic is around <strong className="text-[#F4F8FC]">{topHour.hour}</strong> ({topHour.orders} paid orders).{" "}
                {ops.has_prep_timestamps
                  ? `Avg prep: ${ops.avg_prep_minutes}m.`
                  : "Prep timestamps: Data unavailable."}
              </>
            ) : (
              "Hourly ordering pattern unavailable — no paid orders in this window."
            )}
          </div>
        </div>

        {/* Top Food Items Leaderboard */}
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame className="h-4 w-4 text-[#F5B942]" />
              <h3 className="text-sm font-extrabold text-[#F4F8FC]">Top Menu Performers</h3>
            </div>
            <button
              type="button"
              onClick={() => onNavigateSection("analytics_insights")}
              className="inline-flex items-center gap-1 text-[11px] font-bold text-[#20C5D8] hover:underline"
            >
              Full Food BI <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>

          {topItems.length === 0 ? (
            <div className="py-12 text-center text-xs text-[#9BAFC2]">No dish sales in selected period.</div>
          ) : (
            <div className="space-y-2">
              {topItems.map((item: any, idx: number) => {
                const maxQty = Math.max(1, Number(topItems[0]?.quantity_sold || 1));
                const pct = Math.round((Number(item.quantity_sold || 0) / maxQty) * 100);
                return (
                  <div key={item.item_name} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-[#F4F8FC] truncate pr-2">
                        <span className="mr-1.5 font-mono text-[10px] text-[#20C5D8]">#{idx + 1}</span>
                        {item.item_name}
                      </span>
                      <span className="shrink-0 font-bold text-[#9BAFC2]">
                        {item.quantity_sold} sold · <strong className="text-[#22C58B]">{formatCompactInr(item.revenue)}</strong>
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-[#153149] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[#20C5D8] to-[#368BEA]"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* CollegeBites Intelligence Highlights */}
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[#20C5D8]" />
              <h3 className="text-sm font-extrabold text-[#F4F8FC]">CollegeBites Intelligence</h3>
            </div>
            <button
              type="button"
              onClick={() => onNavigateSection("analytics_insights")}
              className="inline-flex items-center gap-1 text-[11px] font-bold text-[#20C5D8] hover:underline"
            >
              All Insights <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>

          {insights.length === 0 ? (
            <div className="rounded-xl bg-[#153149] p-4 text-xs text-[#9BAFC2]">
              No urgent anomalies detected for the selected date range.
            </div>
          ) : (
            <div className="space-y-2.5">
              {insights.slice(0, 3).map((ins: any) => {
                const badgeCls =
                  ins.urgency === "critical" || ins.severity === "critical"
                    ? "bg-[#F06464]/15 text-[#F06464] border-[#F06464]/35"
                    : ins.urgency === "high" || ins.severity === "warning"
                    ? "bg-[#F5B942]/15 text-[#F5B942] border-[#F5B942]/35"
                    : ins.urgency === "positive" || ins.severity === "positive"
                    ? "bg-[#22C58B]/15 text-[#22C58B] border-[#22C58B]/35"
                    : "bg-[#20C5D8]/15 text-[#20C5D8] border-[#20C5D8]/35";
                return (
                  <div
                    key={ins.id}
                    className="rounded-xl border border-[#368BEA]/20 bg-[#153149]/80 p-3 space-y-1"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${badgeCls}`}>
                        {ins.bi_domain || ins.category}
                      </span>
                      <span className="text-[11px] font-extrabold text-[#F4F8FC]">{ins.metric_label}</span>
                    </div>
                    <div className="text-xs font-bold text-[#F4F8FC]">{ins.what_happened || ins.title}</div>
                    <div className="text-[11px] text-[#9BAFC2] leading-snug">
                      <strong className="text-[#20C5D8]">Action:</strong> {ins.recommended_action || ins.detail}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex items-center justify-between rounded-xl border border-[#368BEA]/20 bg-[#0B1929] px-3 py-2 text-[11px] text-[#9BAFC2]">
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5 text-[#22C58B]" />
              Deterministic DB Rules
            </span>
            <button
              type="button"
              onClick={() => onNavigateSection("reports")}
              className="inline-flex items-center gap-1 font-bold text-[#20C5D8] hover:underline"
            >
              <Activity className="h-3 w-3" /> Generate Reports
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
