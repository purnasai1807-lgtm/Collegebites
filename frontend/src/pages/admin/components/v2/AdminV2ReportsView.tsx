import React, { useState } from "react";
import { Calendar, CreditCard, Download, FileSpreadsheet, FileText, Printer, ShoppingBag, Users, Utensils } from "lucide-react";
import { Button } from "../../../../components/ui/Primitives";
import { formatInr, formatPresetLabel } from "./adminTheme";
import { V2PanelHeader } from "./AdminV2Widgets";

interface AdminV2ReportsViewProps {
  report: any;
  preset: string;
  reportQueryCanteen: string;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}

type ReportKind =
  | "daily_sales"
  | "weekly_sales"
  | "monthly_sales"
  | "order_performance"
  | "food_performance"
  | "payment_report"
  | "customer_activity";

export const AdminV2ReportsView: React.FC<AdminV2ReportsViewProps> = ({
  report,
  preset,
  reportQueryCanteen,
  downloadBlob,
}) => {
  const [selectedReport, setSelectedReport] = useState<ReportKind>("daily_sales");

  const sales = report?.sales || {};
  const ops = report?.operations || {};
  const cust = report?.customers || {};
  const pay = report?.payment_stats || {};
  const fin = report?.financial_analytics || {};

  const reportTypes: { key: ReportKind; label: string; desc: string; icon: any }[] = [
    { key: "daily_sales", label: "Daily Sales Report", desc: "Day-by-day orders, completion, and net revenue", icon: Calendar },
    { key: "weekly_sales", label: "Weekly Sales Report", desc: "ISO week-over-week turnover & average spend", icon: Calendar },
    { key: "monthly_sales", label: "Monthly Sales Report", desc: "Monthly consolidated order & revenue ledger", icon: FileSpreadsheet },
    { key: "order_performance", label: "Order Performance Report", desc: "Hourly rush, prep speed & completion breakdown", icon: ShoppingBag },
    { key: "food_performance", label: "Food Performance Report", desc: "Dish-by-dish unit volume & category mix", icon: Utensils },
    { key: "payment_report", label: "Payment Report", desc: "Razorpay/POS channel totals & attempt health", icon: CreditCard },
    { key: "customer_activity", label: "Customer Activity Report", desc: "Registered, active, new & repeat student cohorts", icon: Users },
  ];

  const buildRows = (): { headers: string[]; rows: (string | number)[][] } => {
    switch (selectedReport) {
      case "daily_sales":
        return {
          headers: ["Date", "Paid Orders", "Completed", "Cancelled", "Net Revenue (INR)", "Avg Order Value (INR)"],
          rows: (sales.daily_series || []).map((d: any) => [
            d.date,
            d.orders,
            d.completed_orders,
            d.cancelled_orders,
            Number(d.revenue || 0).toFixed(2),
            Number(d.aov || 0).toFixed(2),
          ]),
        };
      case "weekly_sales":
        return {
          headers: ["Week", "Week Start", "Paid Orders", "Net Revenue (INR)", "Avg Order Value (INR)"],
          rows: (sales.weekly_series || []).map((w: any) => [
            w.week,
            w.week_start,
            w.orders,
            Number(w.revenue || 0).toFixed(2),
            Number(w.aov || 0).toFixed(2),
          ]),
        };
      case "monthly_sales":
        return {
          headers: ["Month", "Paid Orders", "Net Revenue (INR)", "Avg Order Value (INR)"],
          rows: (sales.monthly_series || []).map((m: any) => [
            m.month,
            m.orders,
            Number(m.revenue || 0).toFixed(2),
            Number(m.aov || 0).toFixed(2),
          ]),
        };
      case "order_performance":
        return {
          headers: ["Weekday", "Paid Orders", "Completed", "Cancelled", "Revenue (INR)"],
          rows: (sales.weekday_series || []).map((w: any) => [
            w.weekday,
            w.orders,
            w.completed_orders,
            w.cancelled_orders,
            Number(w.revenue || 0).toFixed(2),
          ]),
        };
      case "food_performance":
        return {
          headers: ["Dish Name", "Qty Sold", "Orders", "Revenue (INR)", "Profitability"],
          rows: (sales.top_items || []).map((t: any) => [
            t.item_name,
            t.quantity_sold,
            t.order_count,
            Number(t.revenue || 0).toFixed(2),
            t.profitability_available ? `₹${Number(t.estimated_profit).toFixed(2)} (${t.estimated_margin_percent}%)` : "Data unavailable",
          ]),
        };
      case "payment_report":
        return {
          headers: ["Payment Method", "Confirmed Orders", "Confirmed Revenue (INR)"],
          rows: (sales.payment_breakdown || []).map((p: any) => [
            String(p.method || "unknown").toUpperCase(),
            p.orders,
            Number(p.amount || 0).toFixed(2),
          ]),
        };
      case "customer_activity":
        return {
          headers: ["Customer Segment / Frequency", "Count"],
          rows: [
            ["Registered Customer Accounts", cust.registered_customers ?? 0],
            ["Active Ordering Customers", cust.active_ordering_customers ?? 0],
            ["New Customers Joined in Range", cust.new_customers ?? 0],
            ["Returning / Repeat Customers", cust.returning_customers ?? 0],
            ["Repeat Purchase Rate (%)", cust.repeat_order_rate_percent ?? 0],
            ...(cust.order_frequency_distribution || []).map((f: any) => [`Frequency: ${f.bucket}`, f.customers]),
          ],
        };
    }
  };

  const { headers, rows } = buildRows();

  const downloadSectionCsv = () => {
    const csv = [
      headers.join(","),
      ...rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `collegebites-${selectedReport}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Automatic Business Reports"
        subtitle={`Real database exports for ${formatPresetLabel(preset, report?.range?.start_date, report?.range?.end_date)} (${report?.range?.start_date} → ${report?.range?.end_date})`}
        rightSlot={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void downloadBlob(`/reports/export/csv${reportQueryCanteen}`, "collegebites-report.csv")}
            >
              <Download className="h-3.5 w-3.5" /> Full CSV
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void downloadBlob(`/reports/export/xlsx${reportQueryCanteen}`, "collegebites-bi-report.xlsx")}
            >
              <FileSpreadsheet className="h-3.5 w-3.5" /> Excel (.xlsx)
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void downloadBlob(`/reports/export/pdf${reportQueryCanteen}`, "collegebites-report.pdf")}
            >
              <FileText className="h-3.5 w-3.5" /> Full PDF
            </Button>
            <Button size="sm" variant="outline" className="no-print" onClick={() => window.print()}>
              <Printer className="h-3.5 w-3.5" /> Print View
            </Button>
          </div>
        }
      />

      {/* 7 Report Cards Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {reportTypes.map((r) => {
          const Icon = r.icon;
          const active = selectedReport === r.key;
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => setSelectedReport(r.key)}
              className={`rounded-2xl border p-4 text-left transition-all ${
                active
                  ? "border-[#20C5D8] bg-[#153149] shadow-lg"
                  : "border-[#368BEA]/20 bg-[#102438] hover:border-[#20C5D8]/45"
              }`}
            >
              <div className="flex items-center gap-2">
                <Icon className={`h-4 w-4 ${active ? "text-[#20C5D8]" : "text-[#9BAFC2]"}`} />
                <span className="text-xs font-extrabold text-[#F4F8FC]">{r.label}</span>
              </div>
              <p className="mt-1.5 text-[11px] text-[#9BAFC2] leading-snug">{r.desc}</p>
            </button>
          );
        })}
      </div>

      {/* Summary Bar */}
      <div className="grid gap-3 sm:grid-cols-4 text-xs">
        <div className="rounded-xl bg-[#102438] border border-[#368BEA]/20 p-3.5">
          <div className="text-[#9BAFC2]">Verified Net Revenue</div>
          <div className="mt-1 text-lg font-black text-[#20C5D8]">{formatInr(fin.verified_net_revenue ?? 0)}</div>
        </div>
        <div className="rounded-xl bg-[#102438] border border-[#368BEA]/20 p-3.5">
          <div className="text-[#9BAFC2]">Confirmed / Completed Orders</div>
          <div className="mt-1 text-lg font-black text-[#F4F8FC]">
            {sales.total_orders ?? 0} / {ops.completed_orders ?? 0}
          </div>
        </div>
        <div className="rounded-xl bg-[#102438] border border-[#368BEA]/20 p-3.5">
          <div className="text-[#9BAFC2]">Payment Success Rate</div>
          <div className="mt-1 text-lg font-black text-[#22C58B]">{pay.success_rate_percent ?? 0}%</div>
        </div>
        <div className="rounded-xl bg-[#102438] border border-[#368BEA]/20 p-3.5">
          <div className="text-[#9BAFC2]">Avg Customer Spend</div>
          <div className="mt-1 text-lg font-black text-[#F4F8FC]">{formatInr(cust.avg_customer_spending ?? 0)}</div>
        </div>
      </div>

      {/* Live Preview Table */}
      <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-extrabold text-[#F4F8FC]">
              {reportTypes.find((t) => t.key === selectedReport)?.label}
            </h3>
            <p className="text-[11px] text-[#9BAFC2]">
              Showing {rows.length} real record row(s) for {report?.range?.start_date} → {report?.range?.end_date}
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={downloadSectionCsv}>
            <Download className="h-3.5 w-3.5" /> Export This Table (CSV)
          </Button>
        </div>

        {rows.length === 0 ? (
          <div className="py-10 text-center text-xs text-[#9BAFC2]">
            No records available in this report for the selected date range.
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[420px]">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#368BEA]/20 text-[11px] uppercase text-[#9BAFC2]">
                  {headers.map((h) => (
                    <th key={h} className="py-2.5 pr-4">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#368BEA]/15">
                {rows.map((r, i) => (
                  <tr key={i} className="hover:bg-[#153149]/50">
                    {r.map((cell, ci) => (
                      <td
                        key={ci}
                        className={`py-2.5 pr-4 ${ci === 0 ? "font-bold text-[#F4F8FC]" : "text-[#9BAFC2]"}`}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
