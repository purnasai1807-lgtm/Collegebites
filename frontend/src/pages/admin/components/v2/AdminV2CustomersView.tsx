import React, { useState } from "react";
import {
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
import { ShieldCheck, Star, UserCheck, Users } from "lucide-react";
import { CB_V2, V2_CHART_AXIS_TICK, V2_TOOLTIP_STYLE, formatInr } from "./adminTheme";
import { MetricInfoTooltip, V2PanelHeader } from "./AdminV2Widgets";
import { OrdersUsersTab } from "../OrdersUsersTab";

interface AdminV2CustomersViewProps {
  report: any;
  activeCanteenId: string;
  syncStatus: any;
  lastSyncedAt: Date | null;
  triggerSync: () => void;
}

export const AdminV2CustomersView: React.FC<AdminV2CustomersViewProps> = ({
  report,
  activeCanteenId,
  syncStatus,
  lastSyncedAt,
  triggerSync,
}) => {
  const [subView, setSubView] = useState<"intelligence" | "accounts">("intelligence");

  const cust = report?.customers || {};
  const splitData = [
    { name: "Returning Customers", value: Number(cust.returning_customers || 0), fill: CB_V2.success },
    { name: "One-Time Buyers", value: Number(cust.one_time_customers || 0), fill: CB_V2.accentBlue },
  ].filter((d) => d.value > 0);

  const freqDist = cust.order_frequency_distribution || [];
  const ratingDistData = [5, 4, 3, 2, 1].map((star) => ({
    star: `${star}★`,
    count: Number(cust.rating_distribution?.[String(star)] || 0),
  }));

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Customers & Retention Intelligence"
        subtitle="Understand campus student adoption, repeat purchasing habits, satisfaction trends, and account permissions."
        rightSlot={
          <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
            <button
              type="button"
              onClick={() => setSubView("intelligence")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subView === "intelligence" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Customer Intelligence
            </button>
            <button
              type="button"
              onClick={() => setSubView("accounts")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subView === "accounts" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Accounts, Roles &amp; Permissions
            </button>
          </div>
        }
      />

      {subView === "accounts" ? (
        <OrdersUsersTab
          activeCanteenId={activeCanteenId}
          syncStatus={syncStatus}
          lastSyncedAt={lastSyncedAt}
          triggerSync={triggerSync}
          sectionMode="users"
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-[#9BAFC2]">
                <span>Registered Customers</span>
                <Users className="h-3.5 w-3.5 text-[#20C5D8]" />
              </div>
              <div className="mt-1.5 text-2xl font-black text-[#F4F8FC]">{cust.registered_customers ?? 0}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">{cust.new_customers ?? 0} joined in selected window</div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-[#9BAFC2]">
                <span>Active Ordering Customers</span>
                <MetricInfoTooltip metricKey="active_customers" />
              </div>
              <div className="mt-1.5 text-2xl font-black text-[#20C5D8]">{cust.active_ordering_customers ?? 0}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                Avg {cust.avg_orders_per_customer ?? 0} orders per buyer
              </div>
            </div>

            <div className="rounded-2xl border border-[#22C58B]/30 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-[#22C58B]">
                <span>Repeat Customers</span>
                <MetricInfoTooltip metricKey="repeat_customers" />
              </div>
              <div className="mt-1.5 text-2xl font-black text-[#22C58B]">
                {cust.returning_customers ?? 0}{" "}
                <span className="text-sm font-bold">({cust.repeat_order_rate_percent ?? 0}%)</span>
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                Placed more than 1 paid order in range
              </div>
            </div>

            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-[#9BAFC2]">
                <span>Avg Spending / Customer</span>
                <UserCheck className="h-3.5 w-3.5 text-[#368BEA]" />
              </div>
              <div className="mt-1.5 text-2xl font-black text-[#F4F8FC]">
                {formatInr(cust.avg_customer_spending ?? 0)}
              </div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">
                High-value segment: {cust.high_value_customers_count ?? 0} buyers ({formatInr(cust.high_value_customers_spend ?? 0)})
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* New / One-time vs Returning Split */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">Customer Retention Split</h3>
                  <p className="text-[11px] text-[#9BAFC2]">Repeat customers vs single-order customers.</p>
                </div>
                <MetricInfoTooltip metricKey="repeat_customers" />
              </div>
              {splitData.length === 0 ? (
                <div className="h-52 flex items-center justify-center text-xs text-[#9BAFC2]">
                  Data unavailable — no customer orders in selected range.
                </div>
              ) : (
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={splitData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={48}
                        outerRadius={76}
                        paddingAngle={3}
                      >
                        {splitData.map((entry, idx) => (
                          <Cell key={`cs-${idx}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Order Frequency Distribution */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="mb-3">
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Customer Ordering Frequency</h3>
                <p className="text-[11px] text-[#9BAFC2]">Distribution of how many orders each active student placed.</p>
              </div>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={freqDist}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="bucket" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                    <Bar isAnimationActive={false} dataKey="customers" name="Customers" fill="#20C5D8" radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Satisfaction Trend */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-extrabold text-[#F4F8FC]">Student Food Rating Trend</h3>
                  <p className="text-[11px] text-[#9BAFC2]">
                    Average score: ★ {cust.average_food_rating ?? 0} across {cust.review_count ?? 0} reviews
                  </p>
                </div>
                <Star className="h-4 w-4 text-[#F5B942]" />
              </div>
              {(cust.satisfaction_trends || []).length === 0 ? (
                <div className="h-48 flex items-center justify-center text-xs text-[#9BAFC2]">
                  No student review ratings submitted during this period.
                </div>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={cust.satisfaction_trends}>
                      <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={V2_CHART_AXIS_TICK} />
                      <YAxis domain={[0, 5]} tick={V2_CHART_AXIS_TICK} />
                      <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                      <Line isAnimationActive={false} type="monotone" dataKey="avg_rating" name="Avg Rating" stroke="#F5B942" strokeWidth={2.5} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Rating Distribution */}
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">Star Rating Breakdown (1★ – 5★)</h3>
                <span className="inline-flex items-center gap-1 text-[11px] text-[#9BAFC2]">
                  <ShieldCheck className="h-3.5 w-3.5 text-[#22C58B]" /> Privacy-safe aggregate view
                </span>
              </div>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={ratingDistData}>
                    <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="star" tick={V2_CHART_AXIS_TICK} />
                    <YAxis tick={V2_CHART_AXIS_TICK} />
                    <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                    <Bar isAnimationActive={false} dataKey="count" name="Reviews" fill="#F5B942" radius={[5, 5, 0, 0]} />
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
