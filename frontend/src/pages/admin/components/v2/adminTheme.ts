export const CB_V2 = {
  bgMain: "#071321",
  bgSidebar: "#0B1929",
  bgCard: "#102438",
  bgSecondary: "#153149",
  accentCyan: "#20C5D8",
  accentBlue: "#368BEA",
  success: "#22C58B",
  warning: "#F5B942",
  danger: "#F06464",
  textPrimary: "#F4F8FC",
  textSecondary: "#9BAFC2",
  violet: "#8B5CF6",
  gridStroke: "rgba(155, 175, 194, 0.14)",
} as const;

export const V2_PIE_COLORS = [
  "#20C5D8",
  "#368BEA",
  "#22C58B",
  "#F5B942",
  "#8B5CF6",
  "#F06464",
];

export const V2_CHART_AXIS_TICK = {
  fontSize: 11,
  fill: "#9BAFC2",
};

export const V2_TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: "#0B1929",
  borderColor: "rgba(32, 197, 216, 0.35)",
  borderWidth: 1,
  color: "#F4F8FC",
  borderRadius: 12,
  fontSize: 12,
  boxShadow: "0 12px 32px rgba(3, 10, 20, 0.7)",
};

export type AdminSectionId =
  | "overview"
  | "live_orders"
  | "order_history"
  | "menu"
  | "categories"
  | "inventory"
  | "kitchen"
  | "customers"
  | "payments"
  | "finance"
  | "analytics_insights"
  | "reports"
  | "notifications"
  | "settings";

export const DATE_PRESETS = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last_7_days", label: "Last 7 days" },
  { key: "last_30_days", label: "Last 30 days" },
  { key: "this_month", label: "This month" },
  { key: "previous_month", label: "Previous month" },
  { key: "custom", label: "Custom range" },
] as const;

export const METRIC_EXPLANATIONS: Record<
  string,
  { title: string; summary: string; formula?: string }
> = {
  total_revenue: {
    title: "Total Net Revenue",
    summary: "Verified income from confirmed paid orders minus recorded refunds. Unpaid and failed attempts are excluded.",
    formula: "Sum of Order.total_amount where payment_status = CONFIRMED",
  },
  total_orders: {
    title: "Total Confirmed Orders",
    summary: "Count of orders that completed verified payment during the selected window.",
  },
  completed_orders: {
    title: "Completed Orders",
    summary: "Orders that were prepared and handed over to the student at pickup.",
  },
  pending_orders: {
    title: "Active & Pending Orders",
    summary: "Orders currently waiting in queue, being prepared, or awaiting pickup handoff right now.",
  },
  aov: {
    title: "Average Order Value (AOV)",
    summary: "How much money students spend on average per confirmed order.",
    formula: "Total Net Revenue ÷ Total Confirmed Orders",
  },
  active_customers: {
    title: "Active Customers",
    summary: "Registered customer accounts that placed at least one paid order in this period.",
  },
  completion_rate: {
    title: "Order Completion Rate",
    summary: "Percentage of confirmed orders that have already been successfully completed and handed over.",
  },
  cancellation_rate: {
    title: "Cancellation Rate",
    summary: "Percentage of all created orders in this period that were cancelled or rejected.",
  },
  repeat_customers: {
    title: "Repeat Customers",
    summary: "Customers who have placed more than one confirmed order during the selected period.",
  },
  payment_success_rate: {
    title: "Payment Success Rate",
    summary: "Percentage of Razorpay and Counter POS payment attempts that succeeded.",
  },
  revenue_growth: {
    title: "Revenue Growth",
    summary: "How much verified net revenue increased or decreased compared with the previous equivalent date window.",
  },
  gross_order_value: {
    title: "Gross Order Value",
    summary: "Combined value of all orders created (including unpaid/pending/cancelled) vs verified collected money.",
  },
  net_collected: {
    title: "Net Collected Revenue",
    summary: "Actual money confirmed by Razorpay or Counter POS minus any recorded refunds (₹0.00 under strict no-refund policy).",
  },
};

export function formatInr(value: number | string | null | undefined, fallback = "Data unavailable"): string {
  if (value === null || value === undefined || value === "") return fallback;
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return `₹${num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatCompactInr(value: number | string | null | undefined): string {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "₹0";
  return `₹${num.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatPresetLabel(preset: string, start?: string, end?: string): string {
  const match = DATE_PRESETS.find((p) => p.key === preset);
  if (preset === "custom" && start && end) return `${start} → ${end}`;
  return match?.label || `${start || ""} → ${end || ""}`;
}
