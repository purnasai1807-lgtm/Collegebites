import React, { Suspense, lazy, useState } from "react";
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
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowUpRight, DollarSign, FileText, Layers, ShieldAlert, TrendingUp } from "lucide-react";
import {
  type AdminSectionId,
  CB_V2,
  V2_CHART_AXIS_TICK,
  V2_PIE_COLORS,
  V2_TOOLTIP_STYLE,
  formatInr,
} from "./adminTheme";
import { MetricInfoTooltip, V2PanelHeader } from "./AdminV2Widgets";

const MealPlansEventsInvoicesTab = lazy(() =>
  import("../MealPlansEventsInvoicesTab").then((m) => ({ default: m.MealPlansEventsInvoicesTab }))
);

interface AdminV2FinanceViewProps {
  report: any;
  activeCanteenId: string;
  menuItems: any[];
  downloadBlob: (url: string, filename: string) => Promise<void>;
  onNavigateSection: (sec: AdminSectionId) => void;
}

export const AdminV2FinanceView: React.FC<AdminV2FinanceViewProps> = ({
  report,
  activeCanteenId,
  menuItems,
  downloadBlob,
  onNavigateSection,
}) => {
  const [subView, setSubView] = useState<"analytics" | "invoices_plans">("analytics");
  const [granularity, setGranularity] = useState<"daily" | "weekly" | "monthly" | "hourly">("daily");

  const fin = report?.financial_analytics || {};
  const sales = report?.sales || {};
  const pay = report?.payment_stats || {};
  const ops = report?.operations || {};

  const trendData =
    granularity === "weekly"
      ? sales.weekly_series || []
      : granularity === "monthly"
      ? sales.monthly_series || []
      : granularity === "hourly"
      ? (sales.hourly_series || []).filter(
          (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
        )
      : sales.daily_series || [];
  const xKey = granularity === "weekly" ? "week" : granularity === "monthly" ? "month" : granularity === "hourly" ? "hour" : "date";

  const marginAvailable =
    fin.estimated_gross_margin !== null &&
    fin.estimated_gross_margin !== undefined &&
    fin.margin_classification !== "unavailable";

  const peakRevHours = (ops.peak_hours || []).slice(0, 6);
  const topRevPeriod = peakRevHours[0];

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Finance & Revenue Intelligence"
        subtitle="Strict separation between created order values, verified payment collections, refunds, and direct ingredient costs."
        rightSlot={
          <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
            <button
              type="button"
              onClick={() => setSubView("analytics")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subView === "analytics" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Revenue &amp; Margin Analytics
            </button>
            <button
              type="button"
              onClick={() => setSubView("invoices_plans")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subView === "invoices_plans" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Meal Plans, Events &amp; Tax Invoices
            </button>
          </div>
        }
      />

      {subView === "invoices_plans" ? (
        <Suspense
          fallback={
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
              Loading Meal Plans, Events &amp; Tax Invoices...
            </div>
          }
        >
          <MealPlansEventsInvoicesTab
            activeCanteenId={activeCanteenId}
            menuItems={menuItems}
            downloadBlob={downloadBlob}
          />
        </Suspense>
      ) : (
        <>
          {/* Truth-Preserving Financial Distinction Strip */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#9BAFC2]">
                <span>Gross Order Value</span>
                <MetricInfoTooltip metricKey="gross_order_value" />
              </div>
              <div className="mt-2 text-2xl font-black text-[#F4F8FC]">
                {formatInr(fin.gross_order_value_all ?? fin.verified_gross_sales)}
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                All {sales.total_created_orders ?? 0} created orders (paid + unpaid + cancelled)
              </div>
            </div>

            <div className="rounded-2xl border border-[#22C58B]/30 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#22C58B]">
                <span>Successful Payments</span>
                <MetricInfoTooltip metricKey="payment_success_rate" />
              </div>
              <div className="mt-2 text-2xl font-black text-[#22C58B]">
                {formatInr(fin.collected_payments ?? pay.confirmed_amount ?? 0)}
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                {pay.confirmed_count ?? 0} confirmed captures · {pay.success_rate_percent ?? 0}% success rate
              </div>
            </div>

            <div className="rounded-2xl border border-[#20C5D8]/35 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#20C5D8]">
                <span>Net Collected Amount</span>
                <MetricInfoTooltip metricKey="net_collected" />
              </div>
              <div className="mt-2 text-2xl font-black text-[#20C5D8]">
                {formatInr(fin.verified_net_revenue ?? sales.net_sales ?? 0)}
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                Verified net collections after ₹{fin.refunds_amount ?? "0.00"} recorded refunds
              </div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#9BAFC2]">
                <span>Est. Gross Margin</span>
                <DollarSign className="h-3.5 w-3.5 text-[#9BAFC2]" />
              </div>
              <div className="mt-2 text-2xl font-black text-[#F4F8FC]">
                {marginAvailable
                  ? `${formatInr(fin.estimated_gross_margin)} (${fin.estimated_gross_margin_percent}%)`
                  : "Data unavailable"}
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                {marginAvailable
                  ? `After ₹${fin.total_recorded_direct_costs} direct stock + waste cost`
                  : "Insufficient verified ingredient unit-cost entries"}
              </div>
            </div>
          </div>

          {/* Failed, Pending, Refunds & Taxes Secondary Bar */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#153149] p-3.5">
              <div className="text-[11px] text-[#9BAFC2]">Verified Gross Sales (Subtotal)</div>
              <div className="mt-1 text-base font-extrabold text-[#F4F8FC]">{formatInr(fin.verified_gross_sales ?? 0)}</div>
            </div>
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#153149] p-3.5">
              <div className="text-[11px] text-[#9BAFC2]">Pending Payments</div>
              <div className="mt-1 text-base font-extrabold text-[#F5B942]">
                {formatInr(pay.pending_amount ?? 0)} <span className="text-xs font-semibold">({pay.pending_count ?? 0})</span>
              </div>
            </div>
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#153149] p-3.5">
              <div className="text-[11px] text-[#9BAFC2]">Failed Payments</div>
              <div className="mt-1 text-base font-extrabold text-[#F06464]">
                {formatInr(pay.failed_amount ?? 0)} <span className="text-xs font-semibold">({pay.failed_count ?? 0})</span>
              </div>
            </div>
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#153149] p-3.5">
              <div className="text-[11px] text-[#9BAFC2]">Recorded Refunds</div>
              <div className="mt-1 text-base font-extrabold text-[#F4F8FC]">
                {formatInr(fin.refunds_amount ?? 0)} <span className="text-[10px] text-[#9BAFC2]">({fin.refunded_count ?? 0})</span>
              </div>
            </div>
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#153149] p-3.5">
              <div className="text-[11px] text-[#9BAFC2]">Statutory Taxes Collected</div>
              <div className="mt-1 text-base font-extrabold text-[#F4F8FC]">{formatInr(fin.historical_taxes ?? 0)}</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#F5B942]/30 bg-[#F5B942]/10 px-4 py-2.5 text-xs text-[#F4F8FC]">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-[#F5B942] shrink-0" />
              <span>
                Strict No-In-App-Refunds Policy Active · Verified collections are tracked separately from unpaid checkouts.{" "}
                {topRevPeriod && (
                  <>
                    Highest revenue hour: <strong className="text-[#20C5D8]">{topRevPeriod.hour}</strong> ({formatInr(topRevPeriod.revenue)}).
                  </>
                )}
              </span>
            </div>
            <button
              type="button"
              onClick={() => onNavigateSection("payments")}
              className="inline-flex items-center gap-1 font-bold text-[#20C5D8] hover:underline"
            >
              Inspect Transactions <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Primary Revenue Charts */}
          <div className="grid gap-4 lg:grid-cols-12">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-8">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-[#20C5D8]" />
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">
                    Revenue Trend &amp; Order Volume ({granularity.charAt(0).toUpperCase() + granularity.slice(1)})
                  </h3>
                </div>
                <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
                  {(["daily", "weekly", "monthly", "hourly"] as const).map((g) => (
                    <button
                      key={g}
                      type="button"
                      onClick={() => setGranularity(g)}
                      className={`rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                        granularity === g ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                      }`}
                    >
                      {g.charAt(0).toUpperCase() + g.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={trendData}>
                    <defs>
                      <linearGradient id="finArea" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#20C5D8" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#20C5D8" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey={xKey} tick={V2_CHART_AXIS_TICK} />
                    <YAxis yAxisId="r" tick={V2_CHART_AXIS_TICK} />
                    <YAxis yAxisId="o" orientation="right" tick={V2_CHART_AXIS_TICK} />
                    <Tooltip
                      contentStyle={V2_TOOLTIP_STYLE}
                      formatter={(v: any, name: any) => (String(name).includes("Revenue") ? formatInr(v) : v)}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                    <Area
                      isAnimationActive={false}
                      yAxisId="r"
                      type="monotone"
                      dataKey="revenue"
                      name="Net Revenue (₹)"
                      stroke="#20C5D8"
                      strokeWidth={2.5}
                      fill="url(#finArea)"
                    />
                    <Bar
                      isAnimationActive={false}
                      yAxisId="o"
                      dataKey="orders"
                      name="Paid Orders"
                      fill="#368BEA"
                      radius={[4, 4, 0, 0]}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-4">
              <div className="flex items-center gap-2 mb-3">
                <Layers className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Payment Method Split</h3>
              </div>
              {(sales.payment_breakdown || []).length === 0 ? (
                <div className="h-56 flex items-center justify-center text-xs text-[#9BAFC2]">
                  No confirmed transactions in range.
                </div>
              ) : (
                <div className="h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={sales.payment_breakdown}
                        dataKey="amount"
                        nameKey="method"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={3}
                      >
                        {(sales.payment_breakdown || []).map((_e: any, idx: number) => (
                          <Cell key={`fp-${idx}`} fill={V2_PIE_COLORS[idx % V2_PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} formatter={(v: any) => formatInr(v)} />
                      <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          {/* Average Order Value Trend + Peak Revenue Hours */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">Average Order Value (AOV) Trend</h3>
                  <p className="text-[11px] text-[#9BAFC2]">Tracks average student basket spend over time.</p>
                </div>
                <MetricInfoTooltip metricKey="aov" />
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sales.daily_series || []}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} formatter={(v: any) => formatInr(v)} />
                    <Line
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="aov"
                      name="Avg Basket (₹)"
                      stroke="#22C58B"
                      strokeWidth={2.5}
                      dot={{ r: 2.5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">Revenue by Day of Week</h3>
                  <p className="text-[11px] text-[#9BAFC2]">Helps identify which campus days drive peak turnover.</p>
                </div>
                <FileText className="h-4 w-4 text-[#368BEA]" />
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={sales.weekday_series || []}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="weekday" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} formatter={(v: any) => formatInr(v)} />
                    <Bar isAnimationActive={false} dataKey="revenue" name="Revenue (₹)" fill="#368BEA" radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
