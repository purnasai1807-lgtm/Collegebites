import React, { memo, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  Download,
  FilterX,
  Info,
  Layers,
  Moon,
  PackageX,
  Printer,
  RefreshCw,
  Search,
  ShoppingBag,
  Sparkles,
  Sun,
  TrendingUp,
  Users,
} from "lucide-react";
import { api } from "../../../api/client";
import { useDebouncedValue } from "../../../hooks/useDebouncedValue";
import { Badge, Button, Card, Input } from "../../../components/ui/Primitives";

const PIE_COLORS = ["#76010d", "#0f766e", "#1d4ed8", "#d97706", "#7c3aed", "#be123c"];
const LINE_COLORS = ["#76010d", "#0f766e", "#2563eb", "#d97706", "#7c3aed"];

interface BiAnalyticsPanelProps {
  report: any;
  isCollegeAdmin: boolean;
  scopeReportToCanteen: boolean;
  setScopeReportToCanteen: (v: boolean) => void;
  reportPreset: string;
  setReportPreset: (v: string) => void;
  reportStartDate: string;
  setReportStartDate: (v: string) => void;
  reportEndDate: string;
  setReportEndDate: (v: string) => void;
  reportCategoryId?: string;
  setReportCategoryId?: (v: string) => void;
  reportFoodItemId?: string;
  setReportFoodItemId?: (v: string) => void;
  reportComparePrevious?: boolean;
  setReportComparePrevious?: (v: boolean) => void;
  categories?: any[];
  menuItems?: any[];
  reportQueryCanteen: string;
  downloadBlob: (url: string, filename: string) => void;
  onRefreshReport?: () => void;
  refreshing?: boolean;
}

interface DrilldownFilter {
  status?: string;
  hour?: number;
  weekday?: number;
  payment_method?: string;
  food_item_id?: string;
  delayed_only?: boolean;
  label?: string;
}

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HEATMAP_HOURS = Array.from({ length: 16 }, (_, i) => i + 7); // 07:00 .. 22:00

export const BiAnalyticsPanel: React.FC<BiAnalyticsPanelProps> = memo(
  ({
    report,
    isCollegeAdmin,
    scopeReportToCanteen,
    setScopeReportToCanteen,
    reportPreset,
    setReportPreset,
    reportStartDate,
    setReportStartDate,
    reportEndDate,
    setReportEndDate,
    reportCategoryId = "",
    setReportCategoryId,
    reportFoodItemId = "",
    setReportFoodItemId,
    reportComparePrevious = false,
    setReportComparePrevious,
    categories = [],
    menuItems = [],
    reportQueryCanteen,
    downloadBlob,
    onRefreshReport,
    refreshing = false,
  }) => {
    const [biTheme, setBiTheme] = useState<"light" | "dark">(() => {
      try {
        return localStorage.getItem("collegebites_bi_theme") === "dark" ? "dark" : "light";
      } catch {
        return "light";
      }
    });
    const isDark = biTheme === "dark";

    useEffect(() => {
      try {
        localStorage.setItem("collegebites_bi_theme", biTheme);
      } catch {
        // ignore storage errors
      }
    }, [biTheme]);

    const [chartPeriod, setChartPeriod] = useState<"daily" | "weekly" | "monthly" | "yearly" | "hourly">("daily");
    const [productChartMode, setProductChartMode] = useState<"highest" | "lowest" | "all">("highest");
    const [productSearch, setProductSearch] = useState("");
    const [productSort, setProductSort] = useState<
      "qty_desc" | "qty_asc" | "rev_desc" | "rev_asc" | "orders_desc" | "price_desc" | "name_asc"
    >("qty_desc");
    const [productFilter, setProductFilter] = useState<"all" | "sold" | "zero" | "unavailable">("all");
    const [showAllSlow, setShowAllSlow] = useState(false);
    const [showDefinitions, setShowDefinitions] = useState(false);
    const [detailTab, setDetailTab] = useState<"orders" | "items" | "inventory">("orders");
    const [detailSearch, setDetailSearch] = useState("");
    const debouncedDetailSearch = useDebouncedValue(detailSearch, 300);
    const [itemSortDir, setItemSortDir] = useState<"desc" | "asc">("desc");
    const [lowOnly, setLowOnly] = useState(false);
    const [drilldown, setDrilldown] = useState<DrilldownFilter>({});
    const [page, setPage] = useState(1);

    const drilldownSectionRef = useRef<HTMLDivElement | null>(null);

    const applyOrderDrilldown = (filter: DrilldownFilter, targetTab: "orders" | "items" | "inventory" = "orders") => {
      setDetailTab(targetTab);
      setPage(1);
      if (targetTab === "inventory") {
        setLowOnly(true);
        setDrilldown({});
      } else {
        setDrilldown(filter);
      }
      setTimeout(() => {
        drilldownSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 60);
    };

    const detailParams = new URLSearchParams(
      reportQueryCanteen.startsWith("?") ? reportQueryCanteen.slice(1) : reportQueryCanteen
    );
    detailParams.set("page", String(page));
    detailParams.set("page_size", "10");
    if (debouncedDetailSearch.trim()) detailParams.set("q", debouncedDetailSearch.trim());
    if (detailTab === "items") detailParams.set("sort", itemSortDir);
    if (detailTab === "inventory" && lowOnly) detailParams.set("low_only", "true");
    if (detailTab === "orders") {
      if (drilldown.status) detailParams.set("status", drilldown.status);
      if (drilldown.hour !== undefined) detailParams.set("hour", String(drilldown.hour));
      if (drilldown.weekday !== undefined) detailParams.set("weekday", String(drilldown.weekday));
      if (drilldown.payment_method) detailParams.set("payment_method", drilldown.payment_method);
      if (drilldown.food_item_id) detailParams.set("food_item_id", drilldown.food_item_id);
      if (drilldown.delayed_only) detailParams.set("delayed_only", "true");
    }

    const { data: detailData, isLoading: detailLoading, isError: detailError } = useQuery<any>({
      queryKey: ["bi-details", detailTab, detailParams.toString()],
      staleTime: 15_000,
      queryFn: async () => (await api.get(`/reports/details/${detailTab}?${detailParams.toString()}`)).data,
    });

    const presets = [
      { key: "today", label: "Today" },
      { key: "yesterday", label: "Yesterday" },
      { key: "last_7_days", label: "Last 7 Days" },
      { key: "last_30_days", label: "Last 30 Days" },
      { key: "this_month", label: "This Month" },
      { key: "previous_month", label: "Prev Month" },
      { key: "custom", label: "Custom" },
    ];

    const activeTrendData =
      chartPeriod === "weekly"
        ? report.sales?.weekly_series || []
        : chartPeriod === "monthly"
        ? report.sales?.monthly_series || []
        : chartPeriod === "yearly"
        ? report.sales?.yearly_series || []
        : chartPeriod === "hourly"
        ? (report.sales?.hourly_series || []).filter(
            (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
          )
        : report.sales?.daily_series || [];

    const trendXKey =
      chartPeriod === "weekly"
        ? "week"
        : chartPeriod === "monthly"
        ? "month"
        : chartPeriod === "yearly"
        ? "year"
        : chartPeriod === "hourly"
        ? "hour"
        : "date";

    const nonEmptyHours = (report.sales?.hourly_series || []).filter(
      (h: any) => h.orders > 0 || (Number(h.hour.slice(0, 2)) >= 7 && Number(h.hour.slice(0, 2)) <= 22)
    );

    const heatmapCells: any[] = report.sales?.hourly_heatmap || [];
    const heatmapMax = Math.max(1, ...heatmapCells.map((c: any) => Number(c.orders || 0)));
    const heatmapLookup = new Map<string, any>();
    for (const c of heatmapCells) {
      heatmapLookup.set(`${c.weekday_index}:${c.hour}`, c);
    }

    const allProductsPerf: any[] =
      report.sales?.all_products_performance ||
      report.sales?.top_items ||
      [];
    const highestSelling = report.sales?.highest_selling_item || null;
    const highestRevenue = report.sales?.highest_revenue_item || null;
    const lowestSellingSold = report.sales?.lowest_selling_sold_item || null;
    const zeroSalesCount: number =
      report.sales?.zero_sales_count ??
      allProductsPerf.filter((p) => Number(p.quantity_sold || 0) === 0).length;

    const productChartSource =
      productChartMode === "lowest"
        ? [...allProductsPerf]
            .sort((a, b) => a.quantity_sold - b.quantity_sold || a.revenue - b.revenue || a.item_name.localeCompare(b.item_name))
            .slice(0, 15)
        : productChartMode === "all"
        ? allProductsPerf
        : allProductsPerf.slice(0, 15);

    const topProductBarData = productChartSource.map((t: any) => ({
      ...t,
      short_name: t.item_name.length > 18 ? `${t.item_name.slice(0, 17)}…` : t.item_name,
    }));

    const filteredAllProducts = allProductsPerf
      .filter((p) => {
        if (productFilter === "sold" && Number(p.quantity_sold || 0) <= 0) return false;
        if (productFilter === "zero" && Number(p.quantity_sold || 0) > 0) return false;
        if (productFilter === "unavailable" && p.is_available !== false) return false;
        const q = productSearch.trim().toLowerCase();
        if (q) {
          return (
            String(p.item_name || "").toLowerCase().includes(q) ||
            String(p.category_name || "").toLowerCase().includes(q)
          );
        }
        return true;
      })
      .sort((a, b) => {
        switch (productSort) {
          case "qty_asc":
            return a.quantity_sold - b.quantity_sold || a.revenue - b.revenue || a.item_name.localeCompare(b.item_name);
          case "rev_desc":
            return b.revenue - a.revenue || b.quantity_sold - a.quantity_sold;
          case "rev_asc":
            return a.revenue - b.revenue || a.quantity_sold - b.quantity_sold;
          case "orders_desc":
            return (b.order_count || 0) - (a.order_count || 0) || b.quantity_sold - a.quantity_sold;
          case "price_desc":
            return (b.unit_price || 0) - (a.unit_price || 0);
          case "name_asc":
            return String(a.item_name || "").localeCompare(String(b.item_name || ""));
          case "qty_desc":
          default:
            return b.quantity_sold - a.quantity_sold || b.revenue - a.revenue;
        }
      });

    const exportAllProductsCsv = () => {
      const headers = [
        "Product Name",
        "Category",
        "Unit Price (INR)",
        "Orders",
        "Qty Sold",
        "Avg Qty/Order",
        "Revenue (INR)",
        "Revenue Share (%)",
        "Availability",
        "Estimated Profit (INR)",
      ];
      const rows = filteredAllProducts.map((p) => [
        p.item_name,
        p.category_name || "",
        Number(p.unit_price || 0).toFixed(2),
        p.order_count ?? 0,
        p.quantity_sold ?? 0,
        p.avg_qty_per_order ?? 0,
        Number(p.revenue || 0).toFixed(2),
        p.revenue_share_percent ?? 0,
        p.is_available ? "Available" : "Unavailable",
        p.profitability_available && p.estimated_profit !== null ? Number(p.estimated_profit).toFixed(2) : "N/A",
      ]);
      const csv = [headers.join(","), ...rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))].join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "collegebites-all-products-analytics.csv";
      a.click();
      URL.revokeObjectURL(url);
    };

    const demandKeys: string[] = report.sales?.product_demand_trend_keys || [];
    const demandSeries: any[] = report.sales?.product_demand_trends || [];

    const ratingDistData = [5, 4, 3, 2, 1].map((star) => ({
      star: `${star}★`,
      count: Number(report.customers?.rating_distribution?.[String(star)] || 0),
    }));

    // Theme-aware surface & chart tokens
    const shellCls = isDark
      ? "rounded-3xl bg-slate-950 text-slate-100 p-4 sm:p-5 border border-slate-800 space-y-5"
      : "space-y-5";
    const cardCls = isDark
      ? "bg-slate-900 border-slate-800 text-slate-100"
      : "bg-white border-slate-200 text-slate-900";
    const mutedText = isDark ? "text-slate-400" : "text-slate-500";
    const headingText = isDark ? "text-white" : "text-slate-900";
    const subtleBox = isDark ? "bg-slate-800/70 border-slate-700" : "bg-slate-50 border-slate-200";
    const gridStroke = isDark ? "#334155" : "#e2e8f0";
    const axisTick = { fontSize: 10, fill: isDark ? "#94a3b8" : "#64748b" };
    const tooltipStyle = isDark
      ? { backgroundColor: "#0f172a", borderColor: "#334155", color: "#f8fafc", borderRadius: 10, fontSize: 12 }
      : { backgroundColor: "#ffffff", borderColor: "#e2e8f0", color: "#0f172a", borderRadius: 10, fontSize: 12 };

    const activeDrilldownCount =
      Number(Boolean(drilldown.status)) +
      Number(drilldown.hour !== undefined) +
      Number(drilldown.weekday !== undefined) +
      Number(Boolean(drilldown.payment_method)) +
      Number(Boolean(drilldown.food_item_id)) +
      Number(Boolean(drilldown.delayed_only)) +
      Number(lowOnly);

    const formattedTimestamp = report.generated_at
      ? new Date(report.generated_at).toLocaleString("en-IN", { timeZone: report.timezone || "Asia/Kolkata" })
      : "Live";

    const sectionNav = [
      { id: "sec-overview", label: "1. Overview" },
      { id: "sec-revenue", label: "2. Revenue & AOV" },
      { id: "sec-orders", label: "3. Orders & Peak Hours" },
      { id: "sec-products", label: "4. Food & Menu" },
      { id: "sec-customers", label: "5. Customers" },
      { id: "sec-ops", label: "6. Operations & Waste" },
      { id: "sec-insights", label: "7. Business Insights" },
      { id: "sec-drilldown", label: "8. Drill-Down" },
    ];

    return (
      <div className={shellCls}>
        {/* Enterprise BI Control Bar + Section Jump Nav */}
        <Card className={`p-4 space-y-3 ${cardCls}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className={`text-base font-black tracking-tight ${headingText}`}>
                  Enterprise Business Intelligence Console
                </h2>
                <Badge tone="green">ACTUAL DB METRICS</Badge>
                <span className={`text-[11px] font-mono ${mutedText}`}>
                  Updated: {formattedTimestamp} ({report.timezone || "Asia/Kolkata"})
                </span>
              </div>
              <p className={`text-[11px] mt-0.5 ${mutedText}`}>
                {report.data_source || "Real-time SQL aggregation across verified orders, payments, inventory & reviews."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {onRefreshReport && (
                <Button size="sm" variant="outline" onClick={onRefreshReport} disabled={refreshing}>
                  <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} /> Refresh
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => setShowDefinitions((s) => !s)}>
                <Info className="h-3.5 w-3.5" /> Definitions
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setBiTheme((t) => (t === "dark" ? "light" : "dark"))}
                title="Switch BI Light/Dark Theme"
              >
                {isDark ? <Sun className="h-3.5 w-3.5 text-amber-400" /> : <Moon className="h-3.5 w-3.5" />}
                {isDark ? "Light BI" : "Dark BI"}
              </Button>
            </div>
          </div>

          {showDefinitions && report.metric_definitions && (
            <div className={`rounded-xl border p-3 text-[11px] grid gap-2 sm:grid-cols-2 ${subtleBox}`}>
              {Object.entries(report.metric_definitions).map(([k, v]) => (
                <div key={k}>
                  <span className={`font-bold uppercase ${headingText}`}>{k.replace(/_/g, " ")}:</span>{" "}
                  <span className={mutedText}>{String(v)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Presets & Exports */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/20 pt-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {presets.map((p) => (
                <Button
                  key={p.key}
                  size="sm"
                  variant={reportPreset === p.key ? "secondary" : "outline"}
                  onClick={() => {
                    setReportPreset(p.key);
                    setPage(1);
                    if (p.key !== "custom") {
                      setReportStartDate("");
                      setReportEndDate("");
                    }
                  }}
                >
                  {p.label}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => downloadBlob(`/reports/export/xlsx${reportQueryCanteen}`, "collegebites-bi-report.xlsx")}
              >
                <Download className="h-3.5 w-3.5" /> Excel (.xlsx)
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => downloadBlob(`/reports/export/csv${reportQueryCanteen}`, "collegebites-report.csv")}
              >
                <Download className="h-3.5 w-3.5" /> CSV
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => downloadBlob(`/reports/export/pdf${reportQueryCanteen}`, "collegebites-report.pdf")}
              >
                <Download className="h-3.5 w-3.5" /> PDF
              </Button>
              <Button size="sm" variant="outline" className="no-print" onClick={() => window.print()}>
                <Printer className="h-3.5 w-3.5" /> Print
              </Button>
            </div>
          </div>

          {/* Scope, Category, Product, Compare, Custom Date */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/20 pt-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-3">
              {isCollegeAdmin ? (
                <label className={`flex items-center gap-2 font-semibold cursor-pointer ${mutedText}`}>
                  <input
                    type="checkbox"
                    checked={scopeReportToCanteen}
                    onChange={(e) => {
                      setScopeReportToCanteen(e.target.checked);
                      setPage(1);
                    }}
                  />
                  Filter BI to selected canteen
                </label>
              ) : (
                <span className={`font-semibold ${mutedText}`}>Scoped to assigned canteen</span>
              )}
              {setReportComparePrevious && (
                <label className={`flex items-center gap-1.5 font-semibold cursor-pointer ${mutedText}`}>
                  <input
                    type="checkbox"
                    checked={reportComparePrevious}
                    onChange={(e) => setReportComparePrevious(e.target.checked)}
                  />
                  Compare previous period
                </label>
              )}
              {setReportCategoryId && categories.length > 0 && (
                <select
                  value={reportCategoryId}
                  onChange={(e) => {
                    setReportCategoryId(e.target.value);
                    if (setReportFoodItemId) setReportFoodItemId("");
                  }}
                  aria-label="Filter by category"
                  className={`rounded-lg border px-2 py-1 text-xs ${
                    isDark ? "bg-slate-800 border-slate-700 text-slate-100" : "bg-white border-slate-300 text-slate-900"
                  }`}
                >
                  <option value="">All Categories</option>
                  {categories.map((c: any) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
              {setReportFoodItemId && menuItems.length > 0 && (
                <select
                  value={reportFoodItemId}
                  onChange={(e) => setReportFoodItemId(e.target.value)}
                  aria-label="Filter by menu item"
                  className={`rounded-lg border px-2 py-1 text-xs max-w-[180px] ${
                    isDark ? "bg-slate-800 border-slate-700 text-slate-100" : "bg-white border-slate-300 text-slate-900"
                  }`}
                >
                  <option value="">All Products</option>
                  {menuItems
                    .filter((m: any) => !reportCategoryId || m.category_id === reportCategoryId)
                    .map((m: any) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
              )}
              <span className={`rounded-md px-2 py-0.5 text-[11px] font-mono ${subtleBox}`}>
                Window: {report.range.start_date} → {report.range.end_date}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                type="date"
                value={reportStartDate}
                onChange={(e) => {
                  setReportPreset("custom");
                  setReportStartDate(e.target.value);
                  setPage(1);
                }}
                aria-label="Report start date"
                className={`rounded-lg border px-2 py-1 text-xs ${
                  isDark ? "bg-slate-800 border-slate-700 text-slate-100" : "bg-white border-slate-300 text-slate-900"
                }`}
              />
              <span className="text-slate-400">to</span>
              <input
                type="date"
                value={reportEndDate}
                onChange={(e) => {
                  setReportPreset("custom");
                  setReportEndDate(e.target.value);
                  setPage(1);
                }}
                aria-label="Report end date"
                className={`rounded-lg border px-2 py-1 text-xs ${
                  isDark ? "bg-slate-800 border-slate-700 text-slate-100" : "bg-white border-slate-300 text-slate-900"
                }`}
              />
            </div>
          </div>

          {/* Section Quick-Jump Nav */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {sectionNav.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                  isDark
                    ? "bg-slate-800 text-slate-200 hover:bg-slate-700"
                    : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {s.label}
              </a>
            ))}
          </div>
        </Card>

        {report.empty && (
          <Card className={`p-4 border-amber-300 text-xs font-semibold ${isDark ? "bg-amber-950/40 text-amber-200" : "bg-amber-50 text-amber-900"}`}>
            {report.empty_message || "No confirmed orders available for the selected date range."}
          </Card>
        )}

        {/* ==================== SECTION 1: EXECUTIVE OVERVIEW ==================== */}
        <section id="sec-overview" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
              <TrendingUp className="h-4 w-4 text-[#76010d]" /> 1. Executive Overview
            </h3>
            <span className={`text-[11px] ${mutedText}`}>
              {report.period_comparison
                ? `Compared vs ${report.period_comparison.previous_range.start_date} to ${report.period_comparison.previous_range.end_date}`
                : "Enable 'Compare previous period' above for period-over-period % changes • Click cards to drill down"}
            </span>
          </div>

          {(() => {
            const pc = report.period_comparison;
            const renderDelta = (pct: number | null | undefined, prevStr?: string) => {
              if (!pc) return <span className={`text-[10px] ${mutedText}`}>No prior window comparison</span>;
              if (pct === null || pct === undefined) {
                return <span className={`text-[10px] ${mutedText}`}>{prevStr ? `Prior: ${prevStr}` : "No prior baseline"}</span>;
              }
              return (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold">
                  <Badge tone={pct >= 0 ? "green" : "red"}>
                    {pct >= 0 ? "+" : ""}
                    {pct}%
                  </Badge>
                  {prevStr && <span className={mutedText}>vs {prevStr}</span>}
                </span>
              );
            };
            const topCatProfit = report.sales?.most_profitable_category;
            const topCatRev = report.sales?.best_category_by_revenue;
            return (
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-[#76010d]/40 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ label: "Paid Revenue Orders" }, "orders")}
                >
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>Total Revenue</div>
                  <div className="text-xl font-black text-[#76010d] mt-1">
                    ₹{report.financial_analytics?.verified_net_revenue ?? report.sales?.net_sales ?? "0.00"}
                  </div>
                  <div className="mt-1">{renderDelta(pc?.revenue_change_percent, pc ? `₹${pc.previous_net_revenue}` : undefined)}</div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>Verified paid earnings in range</div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-[#76010d]/40 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ label: "Paid Orders" }, "orders")}
                >
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>Today's Revenue</div>
                  <div className="text-xl font-black text-[#76010d] mt-1">₹{report.today_summary?.revenue_today ?? "0.00"}</div>
                  <div className="mt-1">
                    <Badge tone="slate">{report.today_summary?.total_orders_today ?? 0} orders today</Badge>
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>Cash collected since midnight IST</div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-[#76010d]/40 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ label: "Range Orders" }, "orders")}
                >
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>Total Orders</div>
                  <div className={`text-xl font-black mt-1 ${headingText}`}>{report.sales?.total_orders ?? 0}</div>
                  <div className="mt-1">{renderDelta(pc?.orders_change_percent, pc ? `${pc.previous_orders}` : undefined)}</div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    Created: {report.sales?.total_created_orders ?? report.sales?.total_orders ?? 0} total checkouts
                  </div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-emerald-400 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ status: "COMPLETED", label: "Completed Orders" }, "orders")}
                >
                  <div className="text-[10px] font-bold uppercase tracking-wide text-emerald-600">Completed Orders</div>
                  <div className="text-xl font-black text-emerald-600 mt-1">{report.operations?.completed_orders ?? 0}</div>
                  <div className="mt-1">
                    {renderDelta(pc?.completed_change_percent, pc ? `${pc.previous_completed_orders}` : undefined)}
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    {report.operations?.completion_rate_percent ?? 0}% handover completion rate
                  </div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-amber-400 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ status: "PLACED", label: "Active Placed Orders" }, "orders")}
                >
                  <div className="text-[10px] font-bold uppercase tracking-wide text-amber-600">Pending Orders</div>
                  <div className="text-xl font-black text-amber-600 mt-1">{report.operations?.pending_orders ?? 0}</div>
                  <div className="mt-1">
                    {renderDelta(pc?.pending_change_percent, pc ? `${pc.previous_pending_orders}` : undefined)}
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    Live queue now: {report.today_summary?.active_pending_orders ?? 0} active
                  </div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-red-400 transition ${cardCls}`}
                  onClick={() => applyOrderDrilldown({ status: "CANCELLED", label: "Cancelled & Rejected" }, "orders")}
                >
                  <div className="text-[10px] font-bold uppercase tracking-wide text-red-600">Cancelled Orders</div>
                  <div className="text-xl font-black text-red-600 mt-1">{report.operations?.cancelled_orders ?? 0}</div>
                  <div className="mt-1 flex items-center gap-1 text-[10px]">
                    <Badge tone={(report.operations?.cancellation_rate_percent ?? 0) >= 10 ? "red" : "slate"}>
                      {report.operations?.cancellation_rate_percent ?? 0}% rate
                    </Badge>
                    {pc?.cancellation_rate_diff_points !== null && pc?.cancellation_rate_diff_points !== undefined && (
                      <span className={mutedText}>
                        ({pc.cancellation_rate_diff_points >= 0 ? "+" : ""}
                        {pc.cancellation_rate_diff_points} pts)
                      </span>
                    )}
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>Unpaid drops &amp; rejections</div>
                </Card>

                <Card className={`p-3.5 ${cardCls}`}>
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>Average Order Value</div>
                  <div className={`text-xl font-black mt-1 ${headingText}`}>₹{report.sales?.average_order_value ?? "0.00"}</div>
                  <div className="mt-1">{renderDelta(pc?.aov_change_percent, pc ? `₹${pc.previous_aov}` : undefined)}</div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>Typical spend per paid order</div>
                </Card>

                <Card className={`p-3.5 ${cardCls}`}>
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>Active Customers</div>
                  <div className={`text-xl font-black mt-1 ${headingText}`}>{report.customers?.active_ordering_customers ?? 0}</div>
                  <div className="mt-1">
                    {renderDelta(pc?.active_customers_change_percent, pc ? `${pc.previous_active_customers}` : undefined)}
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    {report.customers?.repeat_order_rate_percent ?? 0}% bought 2+ times
                  </div>
                </Card>

                <Card
                  className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-emerald-400 transition ${cardCls}`}
                  onClick={() =>
                    highestSelling?.food_item_id &&
                    applyOrderDrilldown({ food_item_id: highestSelling.food_item_id, label: highestSelling.item_name }, "orders")
                  }
                >
                  <div className="text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">Best-Selling Item</div>
                  <div className={`text-sm font-black mt-1 truncate ${headingText}`} title={highestSelling?.item_name || ""}>
                    {highestSelling ? highestSelling.item_name : "No sales yet"}
                  </div>
                  <div className="mt-1">
                    <Badge tone="green">
                      {highestSelling ? `${highestSelling.quantity_sold} sold • ${highestSelling.revenue_share_percent ?? 0}% rev` : "0 units"}
                    </Badge>
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    {highestSelling ? `₹${Number(highestSelling.revenue || 0).toFixed(2)} generated` : "Waiting for paid orders"}
                  </div>
                </Card>

                <Card className={`p-3.5 ${cardCls}`}>
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${mutedText}`}>
                    {topCatProfit ? "Most Profitable Category" : "Top Food Category"}
                  </div>
                  <div className={`text-sm font-black mt-1 truncate ${headingText}`}>
                    {topCatProfit ? topCatProfit.category : topCatRev ? topCatRev.category : "Data unavailable"}
                  </div>
                  <div className="mt-1">
                    {topCatProfit ? (
                      <Badge tone="green">
                        ₹{Number(topCatProfit.estimated_profit).toFixed(2)} profit ({topCatProfit.margin_percent ?? 0}%)
                      </Badge>
                    ) : topCatRev ? (
                      <Badge tone="blue">{topCatRev.revenue_share_percent}% of revenue</Badge>
                    ) : (
                      <Badge tone="slate">No category sales</Badge>
                    )}
                  </div>
                  <div className={`text-[10px] mt-1 ${mutedText}`}>
                    {topCatProfit
                      ? "From verified recipe & stock costs"
                      : topCatRev
                      ? `₹${Number(topCatRev.revenue).toFixed(2)} sales (add recipe costs for profit)`
                      : "No confirmed category orders"}
                  </div>
                </Card>
              </div>
            );
          })()}

          {(report.business_insights || []).length > 0 && (
            <div className={`rounded-xl border px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs ${subtleBox}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="red">TOP INSIGHT</Badge>
                <span className={`font-bold ${headingText}`}>{report.business_insights[0].title}</span>
                <span className={mutedText}>— {report.business_insights[0].recommended_action}</span>
              </div>
              <a href="#sec-insights" className="font-bold text-[#76010d] hover:underline whitespace-nowrap">
                All Insights ({report.business_insights.length}) →
              </a>
            </div>
          )}
        </section>

        {/* ==================== SECTION 2: REVENUE INTELLIGENCE ==================== */}
        <section id="sec-revenue" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
              <Layers className="h-4 w-4 text-[#76010d]" /> 2. Revenue Intelligence
            </h3>
            {report.period_comparison && (
              <div className={`text-xs flex flex-wrap items-center gap-2 px-3 py-1 rounded-xl border ${subtleBox}`}>
                <span className={mutedText}>
                  vs {report.period_comparison.previous_range.start_date} to {report.period_comparison.previous_range.end_date}:
                </span>
                <span>
                  Orders: <b>{report.period_comparison.previous_orders}</b>{" "}
                  {report.period_comparison.orders_change_percent !== null && (
                    <Badge tone={report.period_comparison.orders_change_percent >= 0 ? "green" : "red"}>
                      {report.period_comparison.orders_change_percent >= 0 ? "+" : ""}
                      {report.period_comparison.orders_change_percent}%
                    </Badge>
                  )}
                </span>
                <span>
                  Net Rev: <b>₹{report.period_comparison.previous_net_revenue}</b>{" "}
                  {report.period_comparison.revenue_change_percent !== null && (
                    <Badge tone={report.period_comparison.revenue_change_percent >= 0 ? "green" : "red"}>
                      {report.period_comparison.revenue_change_percent >= 0 ? "+" : ""}
                      {report.period_comparison.revenue_change_percent}%
                    </Badge>
                  )}
                </span>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6 text-xs">
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Gross Sales</div>
              <div className={`text-lg font-black mt-0.5 ${headingText}`}>₹{report.financial_analytics?.verified_gross_sales ?? report.sales?.gross_sales}</div>
              <div className={`text-[10px] ${mutedText}`}>Confirmed subtotal</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Collected Payments</div>
              <div className={`text-lg font-black mt-0.5 ${headingText}`}>₹{report.financial_analytics?.collected_payments ?? report.payment_stats?.confirmed_amount}</div>
              <div className={`text-[10px] ${mutedText}`}>Gateway + POS confirmed</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Refunds</div>
              <div className="text-lg font-black text-slate-500 mt-0.5">₹{report.financial_analytics?.refunds_amount ?? "0.00"}</div>
              <div className={`text-[10px] ${mutedText}`}>No in-app refunds policy</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Net Revenue</div>
              <div className="text-lg font-black text-[#76010d] mt-0.5">₹{report.financial_analytics?.verified_net_revenue ?? report.sales?.net_sales}</div>
              <div className={`text-[10px] ${mutedText}`}>Excludes failed/unpaid</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Direct Stock + Waste Costs</div>
              <div className={`text-lg font-black mt-0.5 ${headingText}`}>₹{report.financial_analytics?.total_recorded_direct_costs ?? "0.00"}</div>
              <div className={`text-[10px] ${mutedText}`}>Ing: ₹{report.financial_analytics?.verified_ingredient_cost ?? "0.00"}</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Est. Gross Margin</div>
              <div className="text-lg font-black text-emerald-600 mt-0.5">
                {report.financial_analytics?.estimated_gross_margin !== null && report.financial_analytics?.estimated_gross_margin !== undefined
                  ? `₹${report.financial_analytics.estimated_gross_margin} (${report.financial_analytics.estimated_gross_margin_percent}%)`
                  : "Unavailable"}
              </div>
              <div className={`text-[10px] ${mutedText}`}>{(report.financial_analytics?.margin_classification || "unavailable").toUpperCase()}</div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Revenue Trend LineChart */}
            <Card className={`p-4 lg:col-span-2 ${cardCls}`}>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className={`font-bold text-sm ${headingText}`}>
                  Revenue Trend ({chartPeriod.charAt(0).toUpperCase() + chartPeriod.slice(1)})
                </h4>
                <div className="flex flex-wrap gap-1">
                  {(["hourly", "daily", "weekly", "monthly", "yearly"] as const).map((period) => (
                    <Button
                      key={period}
                      size="sm"
                      variant={chartPeriod === period ? "secondary" : "outline"}
                      onClick={() => setChartPeriod(period)}
                    >
                      {period.charAt(0).toUpperCase() + period.slice(1)}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activeTrendData}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey={trendXKey} tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => `₹${Number(v).toFixed(2)}`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="revenue"
                      name="Net Revenue (₹)"
                      stroke="#76010d"
                      strokeWidth={2.5}
                      dot={{ r: 2.5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>

            {/* Payment Method Donut Chart */}
            <Card className={`p-4 ${cardCls}`}>
              <div className="flex items-center justify-between mb-2">
                <h4 className={`font-bold text-sm ${headingText}`}>Payment Method Distribution</h4>
                <span className={`text-[10px] ${mutedText}`}>Click slice to filter</span>
              </div>
              {(report.sales?.payment_breakdown || []).length === 0 ? (
                <div className={`h-60 flex items-center justify-center text-xs ${mutedText}`}>
                  No confirmed payment transactions in range.
                </div>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={report.sales.payment_breakdown}
                        dataKey="amount"
                        nameKey="method"
                        innerRadius={52}
                        outerRadius={84}
                        paddingAngle={3}
                        onClick={(entry: any) => {
                          if (entry?.method) {
                            applyOrderDrilldown(
                              { payment_method: entry.method, label: `Payment: ${entry.method.toUpperCase()}` },
                              "orders"
                            );
                          }
                        }}
                        className="cursor-pointer"
                      >
                        {(report.sales.payment_breakdown || []).map((_e: any, index: number) => (
                          <Cell key={`pay-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => `₹${Number(v).toFixed(2)}`} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Average Order Value Trend Chart */}
            <Card className={`p-4 ${cardCls}`}>
              <div className="flex items-center justify-between mb-3">
                <h4 className={`font-bold text-sm ${headingText}`}>
                  Average Order Value (AOV) Trend ({chartPeriod === "hourly" ? "Daily" : chartPeriod.charAt(0).toUpperCase() + chartPeriod.slice(1)})
                </h4>
                <span className={`text-[11px] font-semibold ${mutedText}`}>
                  Overall AOV: ₹{report.sales?.average_order_value ?? "0.00"}
                </span>
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={
                      chartPeriod === "weekly"
                        ? report.sales?.weekly_series || []
                        : chartPeriod === "monthly"
                        ? report.sales?.monthly_series || []
                        : chartPeriod === "yearly"
                        ? report.sales?.yearly_series || []
                        : report.sales?.daily_series || []
                    }
                  >
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis
                      dataKey={
                        chartPeriod === "weekly"
                          ? "week"
                          : chartPeriod === "monthly"
                          ? "month"
                          : chartPeriod === "yearly"
                          ? "year"
                          : "date"
                      }
                      tick={axisTick}
                    />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => `₹${Number(v).toFixed(2)}`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="aov"
                      name="Avg Order Value (₹)"
                      stroke="#0f766e"
                      strokeWidth={2.5}
                      dot={{ r: 2.5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>

            {/* Revenue by Cafeteria & Counter + Plain-English Revenue Takeaway */}
            <Card className={`p-4 space-y-3 ${cardCls}`}>
              <div className="flex items-center justify-between">
                <h4 className={`font-bold text-sm ${headingText}`}>Revenue by Cafeteria &amp; Counter</h4>
                <span className={`text-[10px] ${mutedText}`}>Contribution % of confirmed sales</span>
              </div>
              {(report.sales?.canteen_sales || []).length === 0 ? (
                <div className={`text-xs py-6 text-center ${mutedText}`}>No cafeteria revenue recorded in this range.</div>
              ) : (
                <div className="space-y-2 text-xs">
                  {(report.sales.canteen_sales || []).map((cn: any) => (
                    <div key={cn.canteen} className={`rounded-xl border px-3 py-2 flex items-center justify-between ${subtleBox}`}>
                      <div>
                        <div className={`font-bold ${headingText}`}>{cn.canteen}</div>
                        <div className={`text-[11px] ${mutedText}`}>{cn.orders} confirmed orders</div>
                      </div>
                      <div className="text-right">
                        <div className="font-black text-[#76010d]">₹{Number(cn.revenue || 0).toFixed(2)}</div>
                        <Badge tone="green">{cn.revenue_share_percent ?? 0}% share</Badge>
                      </div>
                    </div>
                  ))}
                  {(report.sales?.counter_sales || []).length > 0 && (
                    <div className="pt-1 flex flex-wrap gap-1.5">
                      {(report.sales.counter_sales || []).map((ct: any) => (
                        <Badge key={`${ct.canteen || ""}-${ct.counter}`} tone="slate">
                          {ct.counter}: ₹{Number(ct.revenue || 0).toFixed(0)} ({ct.orders})
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {highestRevenue && (
                <div className={`rounded-xl border px-3 py-2 text-[11px] ${subtleBox}`}>
                  <span className="font-bold">Top Revenue Driver:</span> <b>{highestRevenue.item_name}</b> contributed{" "}
                  <b>{highestRevenue.revenue_share_percent ?? 0}%</b> of range sales (₹{Number(highestRevenue.revenue || 0).toFixed(2)}).
                </div>
              )}
            </Card>
          </div>
        </section>

        {/* ==================== SECTION 3: ORDER INTELLIGENCE & HEATMAP ==================== */}
        <section id="sec-orders" className="space-y-3">
          <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
            <ShoppingBag className="h-4 w-4 text-[#76010d]" /> 3. Order &amp; Peak Hour Intelligence
          </h3>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Average Preparation Time</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>
                {report.operations?.has_prep_timestamps ? `${report.operations.avg_prep_minutes} min` : "Data unavailable"}
              </div>
              <div className={`text-[11px] ${mutedText}`}>
                {report.operations?.has_prep_timestamps ? "Confirmed → Ready kitchen speed" : "No kitchen ready timestamps in window"}
              </div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Average Fulfilment Time</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>
                {report.operations?.has_completion_timestamps
                  ? `${report.operations?.avg_fulfilment_minutes ?? report.operations?.avg_completion_minutes ?? 0} min`
                  : "Data unavailable"}
              </div>
              <div className={`text-[11px] ${mutedText}`}>
                {report.operations?.has_completion_timestamps
                  ? `Pickup wait: ${report.operations?.avg_pickup_wait_minutes ?? 0} min`
                  : "No handover completion timestamps yet"}
              </div>
            </Card>
            <Card
              className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-amber-400 transition ${cardCls}`}
              onClick={() => applyOrderDrilldown({ delayed_only: true, label: "Delayed Orders Only" }, "orders")}
            >
              <div className={mutedText}>Delayed Orders</div>
              <div className="text-xl font-black text-amber-600 mt-0.5">{report.operations?.delayed_orders ?? 0}</div>
              <div className={`text-[11px] ${mutedText}`}>Click to inspect delayed orders</div>
            </Card>
            <Card className={`p-3.5 ${cardCls}`}>
              <div className={mutedText}>Order Status Distribution</div>
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {(report.sales?.order_status_breakdown || []).map((st: any) => (
                  <button
                    key={st.status}
                    type="button"
                    onClick={() => applyOrderDrilldown({ status: st.status, label: `Status: ${st.status}` }, "orders")}
                    className="rounded-md bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[10px] font-bold hover:ring-1 hover:ring-[#76010d]"
                  >
                    {st.status}: {st.count}
                  </button>
                ))}
                {(report.sales?.order_status_breakdown || []).length === 0 && (
                  <span className={`text-[11px] ${mutedText}`}>No orders in window</span>
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Order Volume AreaChart */}
            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Order Volume Trend (Completed vs Cancelled)</h4>
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={report.sales?.daily_series || []}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="orders"
                      name="Paid Orders"
                      stroke="#76010d"
                      fill="#76010d"
                      fillOpacity={0.18}
                    />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="completed_orders"
                      name="Completed"
                      stroke="#059669"
                      fill="#059669"
                      fillOpacity={0.15}
                    />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="cancelled_orders"
                      name="Cancelled"
                      stroke="#dc2626"
                      fill="#dc2626"
                      fillOpacity={0.12}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            {/* Weekday Demand BarChart */}
            <Card className={`p-4 ${cardCls}`}>
              <div className="flex items-center justify-between mb-3">
                <h4 className={`font-bold text-sm ${headingText}`}>Weekday Demand Distribution</h4>
                <span className={`text-[10px] ${mutedText}`}>Click bar to inspect day</span>
              </div>
              <div className="h-60">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={report.sales?.weekday_series || []}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="weekday" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar
                      isAnimationActive={false}
                      dataKey="orders"
                      name="Paid Orders"
                      fill="#76010d"
                      radius={[4, 4, 0, 0]}
                      className="cursor-pointer"
                      onClick={(entry: any) => {
                        if (entry?.weekday_index !== undefined) {
                          applyOrderDrilldown(
                            { weekday: entry.weekday_index, label: `Weekday: ${entry.weekday}` },
                            "orders"
                          );
                        }
                      }}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="completed_orders"
                      name="Completed"
                      fill="#0f766e"
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {/* Peak Ordering Hours Heatmap + Hourly Throughput */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className={`p-4 space-y-3 ${cardCls}`}>
              <div className="flex items-center justify-between">
                <h4 className={`font-bold text-sm ${headingText}`}>Peak Ordering Hours Heatmap (Weekday × Hour)</h4>
                <span className={`text-[10px] ${mutedText}`}>Click any cell to filter orders</span>
              </div>
              <div className="overflow-x-auto">
                <div className="min-w-[540px] space-y-1">
                  <div className="grid grid-cols-[42px_repeat(16,minmax(0,1fr))] gap-1 text-[9px] font-mono text-center">
                    <div />
                    {HEATMAP_HOURS.map((hr) => (
                      <div key={hr} className={mutedText}>
                        {String(hr).padStart(2, "0")}h
                      </div>
                    ))}
                  </div>
                  {WEEKDAY_LABELS.map((wdName, wdIdx) => (
                    <div key={wdName} className="grid grid-cols-[42px_repeat(16,minmax(0,1fr))] gap-1 items-center">
                      <div className={`text-[10px] font-bold ${mutedText}`}>{wdName}</div>
                      {HEATMAP_HOURS.map((hr) => {
                        const cell = heatmapLookup.get(`${wdIdx}:${hr}`);
                        const cnt = Number(cell?.orders || 0);
                        const ratio = cnt / heatmapMax;
                        const cellBg =
                          cnt === 0
                            ? isDark
                              ? "bg-slate-800/70 text-slate-600"
                              : "bg-slate-100 text-slate-300"
                            : ratio >= 0.75
                            ? "bg-[#76010d] text-white font-black"
                            : ratio >= 0.45
                            ? "bg-[#a31d29] text-white font-bold"
                            : ratio >= 0.2
                            ? "bg-amber-400/80 text-slate-950 font-bold"
                            : "bg-emerald-200/80 text-emerald-950 font-semibold";
                        return (
                          <button
                            key={hr}
                            type="button"
                            onClick={() => {
                              if (cnt > 0) {
                                applyOrderDrilldown(
                                  { weekday: wdIdx, hour: hr, label: `${wdName} ${String(hr).padStart(2, "0")}:00` },
                                  "orders"
                                );
                              }
                            }}
                            title={`${wdName} ${String(hr).padStart(2, "0")}:00 — ${cnt} orders (₹${Number(cell?.revenue || 0).toFixed(2)})`}
                            className={`h-6 rounded text-[9px] flex items-center justify-center transition ${cellBg} ${
                              cnt > 0 ? "cursor-pointer hover:ring-1 hover:ring-white" : "cursor-default"
                            }`}
                          >
                            {cnt > 0 ? cnt : ""}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Hourly Order Throughput</h4>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={nonEmptyHours}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="hour" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar
                      isAnimationActive={false}
                      dataKey="orders"
                      name="Paid Orders"
                      fill="#76010d"
                      radius={[4, 4, 0, 0]}
                      className="cursor-pointer"
                      onClick={(entry: any) => {
                        if (entry?.hour) {
                          const hrNum = Number(String(entry.hour).slice(0, 2));
                          applyOrderDrilldown({ hour: hrNum, label: `Hour: ${entry.hour}` }, "orders");
                        }
                      }}
                    />
                    <Bar isAnimationActive={false} dataKey="completed_orders" name="Completed" fill="#059669" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {/* Peak Hour Intelligence & Staffing Card + Orders by Food Category */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className={`p-4 space-y-3 ${cardCls}`}>
              <div className="flex items-center justify-between">
                <h4 className={`font-bold text-sm flex items-center gap-1.5 ${headingText}`}>
                  <Clock className="h-4 w-4 text-[#76010d]" /> Peak Hour Intelligence &amp; Staffing Guide
                </h4>
                {report.operations?.peak_hour_intel?.has_data && (
                  <Badge tone="red">
                    {report.operations.peak_hour_intel.peak_workload_share_percent ?? 0}% peak load
                  </Badge>
                )}
              </div>
              {!report.operations?.peak_hour_intel?.has_data ? (
                <div className={`text-xs py-6 text-center ${mutedText}`}>
                  No confirmed orders in this date window to compute peak rush intelligence.
                </div>
              ) : (
                <div className="space-y-2.5 text-xs">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    <div className={`rounded-xl border p-2.5 ${subtleBox}`}>
                      <div className={`text-[10px] font-bold uppercase ${mutedText}`}>Busiest 2h Window</div>
                      <div className="text-sm font-black text-[#76010d] mt-0.5">
                        {report.operations.peak_hour_intel.peak_window}
                      </div>
                      <div className={`text-[10px] ${mutedText}`}>
                        {report.operations.peak_hour_intel.peak_window_orders} orders
                      </div>
                    </div>
                    <div className={`rounded-xl border p-2.5 ${subtleBox}`}>
                      <div className={`text-[10px] font-bold uppercase ${mutedText}`}>Highest Demand Day</div>
                      <div className={`text-sm font-black mt-0.5 ${headingText}`}>
                        {report.operations.peak_hour_intel.highest_demand_day?.weekday || "—"}
                      </div>
                      <div className={`text-[10px] ${mutedText}`}>
                        {report.operations.peak_hour_intel.highest_demand_day?.orders ?? 0} orders
                      </div>
                    </div>
                    <div className={`rounded-xl border p-2.5 ${subtleBox}`}>
                      <div className={`text-[10px] font-bold uppercase ${mutedText}`}>Peak Prep Speed</div>
                      <div className={`text-sm font-black mt-0.5 ${headingText}`}>
                        {report.operations.peak_hour_intel.peak_avg_prep_minutes !== null &&
                        report.operations.peak_hour_intel.peak_avg_prep_minutes !== undefined
                          ? `${report.operations.peak_hour_intel.peak_avg_prep_minutes} min`
                          : "Data unavailable"}
                      </div>
                      <div className={`text-[10px] ${mutedText}`}>
                        Quiet day: {report.operations.peak_hour_intel.lowest_demand_day?.weekday || "—"} (
                        {report.operations.peak_hour_intel.lowest_demand_day?.orders ?? 0})
                      </div>
                    </div>
                  </div>
                  {(report.operations.peak_hour_intel.lowest_demand_hours || []).length > 0 && (
                    <div className={`text-[11px] ${mutedText}`}>
                      <span className="font-bold">Lowest-demand campus hours:</span>{" "}
                      {(report.operations.peak_hour_intel.lowest_demand_hours || [])
                        .map((lh: any) => `${lh.hour} (${lh.orders})`)
                        .join(" • ")}
                    </div>
                  )}
                  <div className={`rounded-xl border px-3 py-2 text-[11px] ${subtleBox}`}>
                    <span className="font-bold text-[#76010d]">Staffing Action:</span>{" "}
                    {report.operations.peak_hour_intel.staffing_recommendation}
                  </div>
                </div>
              )}
            </Card>

            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Orders &amp; Revenue by Food Category</h4>
              {(report.sales?.category_sales || []).length === 0 ? (
                <div className={`h-52 flex items-center justify-center text-xs ${mutedText}`}>
                  No category orders recorded in this window.
                </div>
              ) : (
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={(report.sales?.category_sales || []).slice(0, 8)} layout="vertical" margin={{ left: 10, right: 16 }}>
                      <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                      <XAxis type="number" tick={axisTick} />
                      <YAxis type="category" dataKey="category" width={110} tick={axisTick} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar isAnimationActive={false} dataKey="order_count" name="Orders" fill="#76010d" radius={[0, 4, 4, 0]} />
                      <Bar isAnimationActive={false} dataKey="quantity" name="Items Sold" fill="#0f766e" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </div>
        </section>

        {/* ==================== SECTION 4: PRODUCT INTELLIGENCE ==================== */}
        <section id="sec-products" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
              <Sparkles className="h-4 w-4 text-[#76010d]" /> 4. Complete Product Sales Analytics ({allProductsPerf.length} Products)
            </h3>
            <span className={`text-[11px] ${mutedText}`}>
              Inspect every product&apos;s highest sales, lowest sales, zero sellers, revenue share &amp; order drill-down
            </span>
          </div>

          {/* Highlight Strip: Highest Qty, Highest Revenue, Lowest Selling (>0), Zero-Sales */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <Card
              className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-emerald-400 transition ${cardCls}`}
              onClick={() => {
                if (highestSelling?.food_item_id) {
                  applyOrderDrilldown({ food_item_id: highestSelling.food_item_id, label: `Highest Qty: ${highestSelling.item_name}` }, "orders");
                }
              }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wide text-emerald-600">Highest Selling (Units)</div>
              <div className={`text-sm font-black mt-1 truncate ${headingText}`}>
                {highestSelling ? highestSelling.item_name : "No sales yet"}
              </div>
              <div className={`text-[11px] mt-0.5 ${mutedText}`}>
                {highestSelling
                  ? `${highestSelling.quantity_sold} sold across ${highestSelling.order_count} orders (₹${Number(highestSelling.revenue).toFixed(2)})`
                  : "0 confirmed item sales"}
              </div>
            </Card>

            <Card
              className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-[#76010d]/40 transition ${cardCls}`}
              onClick={() => {
                if (highestRevenue?.food_item_id) {
                  applyOrderDrilldown({ food_item_id: highestRevenue.food_item_id, label: `Highest Revenue: ${highestRevenue.item_name}` }, "orders");
                }
              }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wide text-[#76010d]">Highest Revenue Product</div>
              <div className={`text-sm font-black mt-1 truncate ${headingText}`}>
                {highestRevenue ? highestRevenue.item_name : "No sales yet"}
              </div>
              <div className={`text-[11px] mt-0.5 ${mutedText}`}>
                {highestRevenue
                  ? `₹${Number(highestRevenue.revenue).toFixed(2)} (${highestRevenue.revenue_share_percent ?? 0}% share · ${highestRevenue.quantity_sold} sold)`
                  : "₹0.00 recorded"}
              </div>
            </Card>

            <Card
              className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-amber-400 transition ${cardCls}`}
              onClick={() => {
                if (lowestSellingSold?.food_item_id) {
                  applyOrderDrilldown({ food_item_id: lowestSellingSold.food_item_id, label: `Lowest Sold (>0): ${lowestSellingSold.item_name}` }, "orders");
                }
              }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wide text-amber-600">Lowest Selling (With Sales)</div>
              <div className={`text-sm font-black mt-1 truncate ${headingText}`}>
                {lowestSellingSold ? lowestSellingSold.item_name : "No paid item sales"}
              </div>
              <div className={`text-[11px] mt-0.5 ${mutedText}`}>
                {lowestSellingSold
                  ? `${lowestSellingSold.quantity_sold} sold · ₹${Number(lowestSellingSold.revenue).toFixed(2)} (${lowestSellingSold.order_count} orders)`
                  : "No items with >0 sales in range"}
              </div>
            </Card>

            <Card
              className={`p-3.5 cursor-pointer hover:ring-2 hover:ring-red-400 transition ${cardCls}`}
              onClick={() => {
                setProductFilter("zero");
                setProductSort("qty_asc");
              }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wide text-red-600">Zero-Sale Active Dishes</div>
              <div className="text-xl font-black text-red-600 mt-1">{zeroSalesCount}</div>
              <div className={`text-[11px] mt-0.5 ${mutedText}`}>
                Out of {allProductsPerf.length} products (click to filter table)
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Products BarChart with Highest / Lowest / All Switcher */}
            <Card className={`p-4 ${cardCls}`}>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className={`font-bold text-sm ${headingText}`}>
                  {productChartMode === "highest"
                    ? "Highest Selling Products (Top 15)"
                    : productChartMode === "lowest"
                    ? "Lowest Selling Products (Bottom 15)"
                    : `All Products Revenue vs Qty (${topProductBarData.length})`}
                </h4>
                <div className="flex flex-wrap gap-1">
                  {[
                    { k: "highest", l: "Highest" },
                    { k: "lowest", l: "Lowest" },
                    { k: "all", l: "All Products" },
                  ].map((m) => (
                    <Button
                      key={m.k}
                      size="sm"
                      variant={productChartMode === m.k ? "secondary" : "outline"}
                      onClick={() => setProductChartMode(m.k as any)}
                    >
                      {m.l}
                    </Button>
                  ))}
                </div>
              </div>
              {topProductBarData.length === 0 ? (
                <div className={`h-60 flex items-center justify-center text-xs ${mutedText}`}>
                  No products found for selected canteen/filters.
                </div>
              ) : (
                <div className="max-h-72 overflow-y-auto pr-1">
                  <div style={{ height: Math.max(256, topProductBarData.length * 28) }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={topProductBarData} layout="vertical" margin={{ left: 10 }}>
                        <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                        <XAxis type="number" tick={axisTick} />
                        <YAxis type="category" dataKey="short_name" width={125} tick={axisTick} />
                        <Tooltip contentStyle={tooltipStyle} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar isAnimationActive={false} dataKey="revenue" name="Revenue (₹)" fill="#76010d" radius={[0, 4, 4, 0]} />
                        <Bar isAnimationActive={false} dataKey="quantity_sold" name="Qty Sold" fill="#0f766e" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </Card>

            {/* Product Demand Trends Multi-Line */}
            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Top 5 Product Demand Trends (Daily Units)</h4>
              {demandKeys.length === 0 || demandSeries.length === 0 ? (
                <div className={`h-64 flex items-center justify-center text-xs ${mutedText}`}>
                  No daily product demand history in range.
                </div>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={demandSeries}>
                      <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={axisTick} />
                      <YAxis tick={axisTick} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
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
            </Card>
          </div>

          {/* Complete Every-Product Sales Analytics Table (All Highest, All Lowest & Zero Sales) */}
          <Card className={`p-4 space-y-3 ${cardCls}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4 className={`font-bold text-sm ${headingText}`}>
                  Every Product Sales Breakdown ({filteredAllProducts.length} of {allProductsPerf.length})
                </h4>
                <p className={`text-[11px] ${mutedText}`}>
                  Complete analytical ledger across every product — sort by highest or lowest qty, revenue, orders, or price
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={exportAllProductsCsv}>
                  <Download className="h-3.5 w-3.5" /> Export Products CSV
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex flex-wrap gap-1">
                {[
                  { k: "all", l: `All (${allProductsPerf.length})` },
                  { k: "sold", l: `Sold (${allProductsPerf.length - zeroSalesCount})` },
                  { k: "zero", l: `Zero Sales (${zeroSalesCount})` },
                  { k: "unavailable", l: "Unavailable" },
                ].map((f) => (
                  <Button
                    key={f.k}
                    size="sm"
                    variant={productFilter === f.k ? "secondary" : "outline"}
                    onClick={() => setProductFilter(f.k as any)}
                  >
                    {f.l}
                  </Button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={productSort}
                  onChange={(e) => setProductSort(e.target.value as any)}
                  aria-label="Sort all products"
                  className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                    isDark ? "bg-slate-800 border-slate-700 text-slate-100" : "bg-white border-slate-300 text-slate-900"
                  }`}
                >
                  <option value="qty_desc">Highest Sales (Qty High → Low)</option>
                  <option value="qty_asc">Lowest Sales (Qty Low → High)</option>
                  <option value="rev_desc">Highest Revenue (₹ High → Low)</option>
                  <option value="rev_asc">Lowest Revenue (₹ Low → High)</option>
                  <option value="orders_desc">Most Orders</option>
                  <option value="price_desc">Highest Price</option>
                  <option value="name_asc">Name (A → Z)</option>
                </select>
                <div className="relative">
                  <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                  <Input
                    value={productSearch}
                    onChange={(e) => setProductSearch(e.target.value)}
                    placeholder="Filter any product..."
                    className="pl-8 w-48"
                  />
                </div>
              </div>
            </div>

            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 z-10">
                  <tr className={`border-b text-[11px] uppercase ${isDark ? "bg-slate-900 border-slate-800 text-slate-400" : "bg-slate-50 border-slate-200 text-slate-500"}`}>
                    <th className="py-2 px-2">#</th>
                    <th className="py-2 pr-3">Product</th>
                    <th className="py-2 pr-3">Category</th>
                    <th className="py-2 pr-3 text-right">Price</th>
                    <th className="py-2 pr-3 text-right">Orders</th>
                    <th className="py-2 pr-3 text-right">Qty Sold</th>
                    <th className="py-2 pr-3 text-right">Avg/Order</th>
                    <th className="py-2 pr-3 text-right">Revenue</th>
                    <th className="py-2 pr-3">Share %</th>
                    <th className="py-2 pr-3 text-right">Est. Profit</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 text-right">Orders</th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                  {filteredAllProducts.map((p: any, idx: number) => (
                    <tr key={p.food_item_id || `${p.item_name}-${idx}`} className={isDark ? "hover:bg-slate-800/40" : "hover:bg-slate-50"}>
                      <td className={`py-2 px-2 font-mono text-[10px] ${mutedText}`}>{idx + 1}</td>
                      <td className={`py-2 pr-3 font-bold ${headingText}`}>{p.item_name}</td>
                      <td className={`py-2 pr-3 ${mutedText}`}>{p.category_name}</td>
                      <td className="py-2 pr-3 text-right">₹{Number(p.unit_price || 0).toFixed(2)}</td>
                      <td className="py-2 pr-3 text-right">{p.order_count ?? 0}</td>
                      <td className="py-2 pr-3 text-right font-extrabold">{p.quantity_sold ?? 0}</td>
                      <td className={`py-2 pr-3 text-right ${mutedText}`}>{p.avg_qty_per_order ?? 0}</td>
                      <td className="py-2 pr-3 text-right font-extrabold text-[#76010d]">₹{Number(p.revenue || 0).toFixed(2)}</td>
                      <td className="py-2 pr-3 min-w-[95px]">
                        <div className="flex items-center gap-1.5">
                          <div className={`h-1.5 flex-1 rounded-full overflow-hidden ${isDark ? "bg-slate-800" : "bg-slate-200"}`}>
                            <div
                              className="h-full bg-[#76010d] rounded-full"
                              style={{ width: `${Math.min(100, Number(p.revenue_share_percent || 0))}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-semibold w-9 text-right">{p.revenue_share_percent ?? 0}%</span>
                        </div>
                      </td>
                      <td className={`py-2 pr-3 text-right text-[11px] ${mutedText}`}>
                        {p.profitability_available && p.estimated_profit !== null
                          ? `₹${Number(p.estimated_profit).toFixed(2)} (${p.estimated_margin_percent}%)`
                          : "N/A"}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge tone={p.is_available ? "green" : p.is_active === false ? "slate" : "amber"}>
                          {p.is_available ? "Available" : p.is_active === false ? "Archived" : "Unavailable"}
                        </Badge>
                      </td>
                      <td className="py-2 text-right">
                        {p.food_item_id && (
                          <button
                            type="button"
                            onClick={() =>
                              applyOrderDrilldown(
                                { food_item_id: p.food_item_id, label: `Product: ${p.item_name}` },
                                "orders"
                              )
                            }
                            className="text-[11px] font-bold text-[#76010d] hover:underline"
                          >
                            Inspect →
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filteredAllProducts.length === 0 && (
                    <tr>
                      <td colSpan={12} className={`py-8 text-center text-xs ${mutedText}`}>
                        No products match the selected filter/search.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Category Donut */}
            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-2 ${headingText}`}>Category Revenue Mix</h4>
              {(report.sales?.category_sales || []).length === 0 ? (
                <div className={`h-52 flex items-center justify-center text-xs ${mutedText}`}>
                  No category sales in range.
                </div>
              ) : (
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={report.sales.category_sales}
                        dataKey="revenue"
                        nameKey="category"
                        innerRadius={45}
                        outerRadius={76}
                        paddingAngle={2}
                      >
                        {(report.sales.category_sales || []).map((_e: any, index: number) => (
                          <Cell key={`cat-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => `₹${Number(v).toFixed(2)}`} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            {/* Frequently Purchased Combinations */}
            <Card className={`p-4 space-y-2 text-xs ${cardCls}`}>
              <div className="flex items-center justify-between">
                <h4 className={`font-bold text-sm ${headingText}`}>Frequently Purchased Combinations</h4>
                <Badge tone="blue">Co-occurrence</Badge>
              </div>
              {(report.sales?.frequent_combinations || []).length === 0 ? (
                <div className={`py-8 text-center ${mutedText}`}>
                  Not enough multi-item orders in selected range to detect pairings.
                </div>
              ) : (
                <div className="space-y-2 pt-1">
                  {(report.sales.frequent_combinations || []).slice(0, 6).map((combo: any) => (
                    <div key={combo.pair_label} className={`flex items-center justify-between rounded-lg border px-2.5 py-2 ${subtleBox}`}>
                      <span className={`font-bold truncate pr-2 ${headingText}`}>{combo.pair_label}</span>
                      <span className="shrink-0">
                        <Badge tone="green">{combo.co_order_count} orders ({combo.support_percent}%)</Badge>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* All Lowest-Selling / Slow Menu Items */}
            <Card className={`p-4 space-y-2 text-xs ${cardCls}`}>
              <div className="flex items-center justify-between">
                <h4 className={`font-bold text-sm ${headingText}`}>All Lowest-Selling / Slow Items ({allProductsPerf.length})</h4>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowAllSlow((v) => !v)}
                    className="text-[11px] font-bold text-[#76010d] hover:underline"
                  >
                    {showAllSlow ? "Collapse" : "Show All"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setItemSortDir("asc");
                      applyOrderDrilldown({}, "items");
                    }}
                    className="text-[11px] font-bold text-[#76010d] hover:underline"
                  >
                    Paginated →
                  </button>
                </div>
              </div>
              <div className={`space-y-1.5 pt-1 ${showAllSlow ? "max-h-64 overflow-y-auto pr-1" : ""}`}>
                {(showAllSlow
                  ? [...allProductsPerf].sort(
                      (a, b) => a.quantity_sold - b.quantity_sold || a.revenue - b.revenue || a.item_name.localeCompare(b.item_name)
                    )
                  : report.sales?.least_ordered_items || []
                ).map((li: any) => (
                  <div
                    key={li.food_item_id}
                    onClick={() =>
                      applyOrderDrilldown(
                        { food_item_id: li.food_item_id, label: `Product: ${li.item_name}` },
                        "orders"
                      )
                    }
                    className={`flex items-center justify-between border-b pb-1.5 cursor-pointer hover:opacity-80 ${
                      isDark ? "border-slate-800" : "border-slate-100"
                    }`}
                  >
                    <div className="truncate pr-2">
                      <span className={`font-bold ${headingText}`}>{li.item_name}</span>
                      <span className={`ml-1.5 text-[10px] ${mutedText}`}>{li.category_name}</span>
                    </div>
                    <Badge tone={li.quantity_sold === 0 ? "amber" : "slate"}>
                      {li.quantity_sold} sold • ₹{Number(li.revenue || 0).toFixed(0)}
                    </Badge>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <Card className={`p-4 space-y-2.5 ${cardCls}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className={`font-bold text-sm ${headingText}`}>Declining Sales Food Items (vs Prior Period)</h4>
                <p className={`text-[11px] ${mutedText}`}>
                  Dishes whose unit sales fell compared with the equivalent previous window — gentle prompts for pricing or visibility review
                </p>
              </div>
              {!report.period_comparison && setReportComparePrevious && (
                <Button size="sm" variant="outline" onClick={() => setReportComparePrevious(true)}>
                  Enable Prior Period Comparison
                </Button>
              )}
            </div>
            {!report.period_comparison ? (
              <div className={`text-xs ${mutedText}`}>
                Turn on <b>Compare previous period</b> in the filter bar above to detect declining dishes automatically.
              </div>
            ) : (report.sales?.declining_items || []).length === 0 ? (
              <div className={`text-xs ${mutedText}`}>No menu items recorded a sales decline compared with the previous period.</div>
            ) : (
              <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3 text-xs">
                {(report.sales.declining_items || []).map((di: any) => (
                  <div
                    key={di.item_name}
                    onClick={() =>
                      di.food_item_id &&
                      applyOrderDrilldown({ food_item_id: di.food_item_id, label: `Declining: ${di.item_name}` }, "orders")
                    }
                    className={`rounded-xl border p-2.5 cursor-pointer hover:ring-1 hover:ring-amber-400 transition ${subtleBox}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`font-bold truncate ${headingText}`}>{di.item_name}</span>
                      <Badge tone="red">{di.qty_change_percent}%</Badge>
                    </div>
                    <div className={`text-[11px] mt-1 ${mutedText}`}>
                      Sold {di.current_quantity} vs {di.previous_quantity} prior ({di.qty_change} units)
                    </div>
                    <div className="text-[10px] mt-1 text-amber-700 dark:text-amber-300">
                      Suggestion: Review portion quality, price, or home banner placement.
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </section>

        {/* ==================== SECTION 5: CUSTOMER INTELLIGENCE ==================== */}
        <section id="sec-customers" className="space-y-3">
          <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
            <Users className="h-4 w-4 text-[#76010d]" /> 5. Customer Intelligence &amp; Satisfaction
          </h3>

          <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 text-xs">
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Registered Customers</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>{report.customers?.registered_customers ?? 0}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Active Customers</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>{report.customers?.active_ordering_customers ?? 0}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>New Customers</div>
              <div className="text-xl font-black text-blue-600 mt-0.5">{report.customers?.new_customers ?? 0}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Returning Customers</div>
              <div className="text-xl font-black text-emerald-600 mt-0.5">{report.customers?.returning_customers ?? 0}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Repeat Purchase Rate</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>{report.customers?.repeat_order_rate_percent ?? 0}%</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Avg Orders / Customer</div>
              <div className={`text-xl font-black mt-0.5 ${headingText}`}>{report.customers?.avg_orders_per_customer ?? 0}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Avg Customer Spend</div>
              <div className="text-xl font-black text-[#76010d] mt-0.5">₹{report.customers?.avg_customer_spending ?? "0.00"}</div>
            </Card>
            <Card className={`p-3 ${cardCls}`}>
              <div className={mutedText}>Feedback Rating</div>
              <div className="text-xl font-black text-amber-500 mt-0.5">
                ★ {report.customers?.average_food_rating ?? 0}
              </div>
              <div className={`text-[10px] ${mutedText}`}>{report.customers?.review_count ?? 0} reviews</div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Customer Growth Trend (New Signups)</h4>
              {(report.customers?.new_customers_trends || []).length === 0 ? (
                <div className={`h-48 flex items-center justify-center text-xs ${mutedText}`}>
                  No customer signup dates available in this range.
                </div>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={report.customers.new_customers_trends}>
                      <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={axisTick} />
                      <YAxis tick={axisTick} allowDecimals={false} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Area
                        isAnimationActive={false}
                        type="monotone"
                        dataKey="new_customers"
                        name="New Students"
                        stroke="#2563eb"
                        fill="#2563eb"
                        fillOpacity={0.2}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Customer Ordering Frequency</h4>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={report.customers?.order_frequency_distribution || []}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="bucket" tick={axisTick} />
                    <YAxis tick={axisTick} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar isAnimationActive={false} dataKey="customers" name="Customers" fill="#76010d" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Customer Satisfaction Trend</h4>
              {(report.customers?.satisfaction_trends || []).length === 0 ? (
                <div className={`h-48 flex items-center justify-center text-xs ${mutedText}`}>
                  No customer review ratings submitted during this period.
                </div>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={report.customers.satisfaction_trends}>
                      <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={axisTick} />
                      <YAxis domain={[0, 5]} tick={axisTick} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Line isAnimationActive={false} type="monotone" dataKey="avg_rating" name="Avg Rating (★)" stroke="#d97706" strokeWidth={2.5} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Rating Distribution (1★ – 5★)</h4>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={ratingDistData}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="star" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar isAnimationActive={false} dataKey="count" name="Reviews" fill="#d97706" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
        </section>

        {/* ==================== SECTION 6: OPERATIONAL INTELLIGENCE ==================== */}
        <section id="sec-ops" className="space-y-3">
          <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
            <Activity className="h-4 w-4 text-[#76010d]" /> 6. Operational, Kitchen, Stock &amp; Wastage Intelligence
          </h3>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Preparation Time Trends */}
            <Card className={`p-4 ${cardCls}`}>
              <div className="flex items-center justify-between mb-3">
                <h4 className={`font-bold text-sm ${headingText}`}>Preparation &amp; Fulfilment Time Trends (min)</h4>
                <Badge tone={(report.operations?.kitchen_workload_percent ?? 0) >= 80 ? "red" : "green"}>
                  Kitchen Load: {report.operations?.kitchen_workload_percent ?? 0}%
                </Badge>
              </div>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={report.sales?.daily_series || []}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line isAnimationActive={false} type="monotone" dataKey="avg_prep_minutes" name="Avg Prep (m)" stroke="#76010d" strokeWidth={2} dot={false} />
                    <Line isAnimationActive={false} type="monotone" dataKey="avg_fulfilment_minutes" name="Avg Fulfilment (m)" stroke="#2563eb" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>

            {/* Inventory Consumption, Restock & Wastage Trend */}
            <Card className={`p-4 ${cardCls}`}>
              <h4 className={`font-bold text-sm mb-3 ${headingText}`}>Inventory Consumption, Restock &amp; Wastage Trend</h4>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={report.inventory?.consumption_trends || []}>
                    <CartesianGrid stroke={gridStroke} strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={axisTick} />
                    <YAxis tick={axisTick} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line isAnimationActive={false} type="monotone" dataKey="consumed_qty" name="Consumed" stroke="#76010d" strokeWidth={2} dot={false} />
                    <Line isAnimationActive={false} type="monotone" dataKey="restocked_qty" name="Restocked" stroke="#059669" strokeWidth={2} dot={false} />
                    <Line isAnimationActive={false} type="monotone" dataKey="wastage_qty" name="Wasted" stroke="#d97706" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3 text-xs">
            {/* Counter Utilization */}
            <Card className={`p-4 space-y-2 ${cardCls}`}>
              <div className="font-bold text-sm">Two-Counter Performance</div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className={`border-b ${isDark ? "border-slate-800 text-slate-400" : "border-slate-200 text-slate-500"}`}>
                      <th className="py-1 pr-2">Counter</th>
                      <th className="py-1 pr-2">Orders</th>
                      <th className="py-1 pr-2">Revenue</th>
                      <th className="py-1">Util</th>
                    </tr>
                  </thead>
                  <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                    {(report.sales?.counter_performance || []).map((c: any) => (
                      <tr key={c.counter_id}>
                        <td className="py-1.5 pr-2 font-semibold">{c.counter_name}</td>
                        <td className="py-1.5 pr-2">{c.orders}</td>
                        <td className="py-1.5 pr-2 font-semibold">₹{Number(c.revenue).toFixed(2)}</td>
                        <td className="py-1.5">
                          <Badge tone={c.utilization_percent >= 80 ? "red" : "green"}>{c.utilization_percent}%</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* Out-of-Stock Products & Low Stock Alerts */}
            <Card className={`p-4 space-y-2 ${cardCls}`}>
              <div className="flex items-center justify-between">
                <div className="font-bold text-sm flex items-center gap-1.5">
                  <PackageX className="h-4 w-4 text-red-600" /> Stockouts &amp; Low Stock
                </div>
                <button
                  type="button"
                  onClick={() => applyOrderDrilldown({}, "inventory")}
                  className="text-[11px] font-bold text-[#76010d] hover:underline"
                >
                  Inspect Stock →
                </button>
              </div>
              <div className={mutedText}>
                Low stock: <b>{report.inventory?.low_stock_count ?? 0}</b> • Out-of-stock dishes:{" "}
                <b>{report.inventory?.out_of_stock_products_count ?? 0}</b> • Expiring 7d:{" "}
                <b>{report.inventory?.expiring_within_7_days ?? 0}</b>
              </div>
              <div className="flex flex-wrap gap-1.5 pt-1">
                {(report.inventory?.low_stock_items || []).slice(0, 6).map((item: any) => (
                  <Badge key={item.inventory_item_id} tone="red">
                    {item.ingredient_name}: {item.current_quantity}/{item.reorder_level} {item.unit}
                  </Badge>
                ))}
                {(report.inventory?.out_of_stock_products || []).slice(0, 5).map((p: any) => (
                  <Badge key={p.food_item_id} tone="amber">
                    {p.item_name} ({p.reason})
                  </Badge>
                ))}
              </div>
            </Card>

            {/* Food Wastage Analytics */}
            <Card className={`p-4 space-y-2 ${cardCls}`}>
              <div className="flex items-center justify-between">
                <div className="font-bold text-sm">Food Wastage &amp; Staff Activity</div>
                <span className="font-black text-red-600">₹{report.inventory?.total_wastage_loss ?? "0.00"}</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                {Object.entries(report.inventory?.wastage_breakdown || {}).map(([k, v]: [string, any]) => (
                  <div key={k} className={`rounded-lg border px-2 py-1.5 ${subtleBox}`}>
                    <div className="uppercase text-[10px] font-bold">{k}</div>
                    <div>
                      {v.quantity} qty • ₹{v.loss_amount}
                    </div>
                  </div>
                ))}
              </div>
              <div className={`text-[11px] pt-1 ${mutedText}`}>
                Staff Check-ins: <b>{report.staff_performance?.present_checkins ?? 0}</b> • Tasks:{" "}
                <b>
                  {report.staff_performance?.tasks_completed ?? 0}/{report.staff_performance?.tasks_total ?? 0}
                </b>
              </div>
            </Card>
          </div>
        </section>

        {/* ==================== SECTION 7: BUSINESS INSIGHTS & RECOMMENDATIONS ==================== */}
        <section id="sec-insights" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className={`text-sm font-extrabold flex items-center gap-2 ${headingText}`}>
              <AlertTriangle className="h-4 w-4 text-[#76010d]" /> 7. Business Insights &amp; Recommendations
            </h3>
            <span className={`text-[11px] ${mutedText}`}>
              Every insight explains What happened, Why it matters &amp; What to do next from live DB data
            </span>
          </div>
          {(report.business_insights || []).length === 0 ? (
            <Card className={`p-4 text-xs ${cardCls} ${mutedText}`}>
              No anomaly or threshold insights triggered for this date window.
            </Card>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {(report.business_insights || []).map((ins: any) => {
                const tone: "green" | "amber" | "red" | "blue" =
                  ins.severity === "critical"
                    ? "red"
                    : ins.severity === "warning"
                    ? "amber"
                    : ins.severity === "positive"
                    ? "green"
                    : "blue";
                return (
                  <Card key={ins.id} className={`p-4 flex flex-col justify-between gap-3 ${cardCls}`}>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <Badge tone={tone}>{ins.bi_domain || ins.category.toUpperCase()}</Badge>
                        <span className="text-[11px] font-black">{ins.metric_label}</span>
                      </div>
                      <div className={`font-extrabold text-sm ${headingText}`}>{ins.title}</div>
                      {ins.time_period && (
                        <div className={`text-[10px] font-mono ${mutedText}`}>Period: {ins.time_period}</div>
                      )}
                      <div className={`text-xs space-y-1.5 ${mutedText}`}>
                        <div>
                          <span className={`font-bold ${headingText}`}>What happened:</span> {ins.what_happened || ins.detail}
                        </div>
                        {ins.why_it_matters && (
                          <div>
                            <span className={`font-bold ${headingText}`}>Why it matters:</span> {ins.why_it_matters}
                          </div>
                        )}
                        {ins.recommended_action && (
                          <div className={`rounded-lg border px-2.5 py-1.5 ${subtleBox}`}>
                            <span className="font-bold text-[#76010d]">Next action:</span> {ins.recommended_action}
                          </div>
                        )}
                        {ins.supporting_data && (
                          <div className="text-[11px]">
                            <span className="font-semibold">Data:</span> {ins.supporting_data}
                          </div>
                        )}
                      </div>
                    </div>
                    {ins.drilldown && (
                      <button
                        type="button"
                        onClick={() =>
                          applyOrderDrilldown(
                            {
                              status: ins.drilldown.status,
                              hour: ins.drilldown.hour,
                              delayed_only: ins.drilldown.delayed_only,
                              label: ins.title,
                            },
                            ins.drilldown.tab || "orders"
                          )
                        }
                        className="inline-flex items-center gap-1 text-xs font-bold text-[#76010d] hover:underline self-start"
                      >
                        Inspect Records <ArrowUpRight className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </Card>
                );
              })}
            </div>
          )}
        </section>

        {/* ==================== SECTION 8: INTERACTIVE DRILL-DOWN RECORDS ==================== */}
        <div id="sec-drilldown" ref={drilldownSectionRef}>
          <Card className={`p-5 space-y-4 ${cardCls}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { key: "orders", label: "Orders Drill-Down" },
                  { key: "items", label: "Menu Item Analytics" },
                  { key: "inventory", label: "Inventory Consumption" },
                ].map((t) => (
                  <Button
                    key={t.key}
                    size="sm"
                    variant={detailTab === t.key ? "secondary" : "outline"}
                    onClick={() => {
                      setDetailTab(t.key as any);
                      setPage(1);
                    }}
                  >
                    {t.label}
                  </Button>
                ))}
                {activeDrilldownCount > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setDrilldown({});
                      setLowOnly(false);
                      setPage(1);
                    }}
                  >
                    <FilterX className="h-3.5 w-3.5 text-red-600" /> Clear Drill-Down ({activeDrilldownCount})
                  </Button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {detailTab === "items" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setItemSortDir((d) => (d === "desc" ? "asc" : "desc"));
                      setPage(1);
                    }}
                  >
                    Sort Qty: {itemSortDir === "desc" ? "High → Low" : "Low → High"}
                  </Button>
                )}
                {detailTab === "inventory" && (
                  <label className={`flex items-center gap-1.5 text-xs font-semibold cursor-pointer ${mutedText}`}>
                    <input
                      type="checkbox"
                      checked={lowOnly}
                      onChange={(e) => {
                        setLowOnly(e.target.checked);
                        setPage(1);
                      }}
                    />
                    Low stock only
                  </label>
                )}
                <div className="relative">
                  <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                  <Input
                    value={detailSearch}
                    onChange={(e) => {
                      setDetailSearch(e.target.value);
                      setPage(1);
                    }}
                    placeholder="Search records..."
                    className="pl-8 w-52"
                  />
                </div>
              </div>
            </div>

            {activeDrilldownCount > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className={mutedText}>Active Drill-Down:</span>
                {drilldown.label && <Badge tone="blue">{drilldown.label}</Badge>}
                {drilldown.status && <Badge tone="red">Status: {drilldown.status}</Badge>}
                {drilldown.weekday !== undefined && <Badge tone="blue">Day: {WEEKDAY_LABELS[drilldown.weekday]}</Badge>}
                {drilldown.hour !== undefined && <Badge tone="blue">Hour: {String(drilldown.hour).padStart(2, "0")}:00</Badge>}
                {drilldown.payment_method && <Badge tone="green">Method: {drilldown.payment_method.toUpperCase()}</Badge>}
                {drilldown.delayed_only && <Badge tone="amber">Delayed Only</Badge>}
                {lowOnly && <Badge tone="red">Low Stock Only</Badge>}
              </div>
            )}

            {detailLoading ? (
              <div className={`py-8 text-center text-xs ${mutedText}`}>
                <Clock className="h-4 w-4 inline animate-spin mr-1.5" /> Loading database records...
              </div>
            ) : detailError ? (
              <div className="py-6 text-center text-xs text-red-500">
                Failed to load drill-down records for the current filter.
              </div>
            ) : (
              <div className="overflow-x-auto">
                {detailTab === "orders" && (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className={`border-b text-[11px] uppercase ${isDark ? "border-slate-800 text-slate-400" : "border-slate-200 text-slate-500"}`}>
                        <th className="py-2 pr-3">Order / Token</th>
                        <th className="py-2 pr-3">Customer</th>
                        <th className="py-2 pr-3">Counter</th>
                        <th className="py-2 pr-3">Status</th>
                        <th className="py-2 pr-3">Method</th>
                        <th className="py-2 pr-3">Prep / Wait</th>
                        <th className="py-2 text-right">Amount</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                      {(detailData?.items || []).map((row: any) => (
                        <tr key={row.order_id}>
                          <td className={`py-2 pr-3 font-bold ${headingText}`}>
                            {row.order_number} {row.token_code ? `• ${row.token_code}` : ""}
                          </td>
                          <td className="py-2 pr-3">{row.customer_name}</td>
                          <td className="py-2 pr-3">{row.counter_name}</td>
                          <td className="py-2 pr-3">
                            <Badge tone={row.status === "COMPLETED" ? "green" : row.status === "CANCELLED" ? "red" : "blue"}>
                              {row.status}
                            </Badge>
                          </td>
                          <td className="py-2 pr-3 uppercase text-[11px]">{row.payment_method}</td>
                          <td className={`py-2 pr-3 ${mutedText}`}>
                            {row.prep_minutes ?? "-"}m / {row.pickup_wait_minutes ?? "-"}m
                          </td>
                          <td className="py-2 text-right font-bold">₹{row.total_amount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {detailTab === "items" && (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className={`border-b text-[11px] uppercase ${isDark ? "border-slate-800 text-slate-400" : "border-slate-200 text-slate-500"}`}>
                        <th className="py-2 pr-3">Dish Name</th>
                        <th className="py-2 pr-3">Category</th>
                        <th className="py-2 pr-3">Unit Price</th>
                        <th className="py-2 pr-3">Orders</th>
                        <th className="py-2 pr-3">Qty Sold</th>
                        <th className="py-2 pr-3">Revenue</th>
                        <th className="py-2 text-right">Availability</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                      {(detailData?.items || []).map((row: any) => (
                        <tr key={row.food_item_id}>
                          <td className={`py-2 pr-3 font-bold ${headingText}`}>{row.item_name}</td>
                          <td className={`py-2 pr-3 ${mutedText}`}>{row.category_name}</td>
                          <td className="py-2 pr-3">₹{row.unit_price}</td>
                          <td className="py-2 pr-3">{row.order_count}</td>
                          <td className="py-2 pr-3 font-bold">{row.quantity_sold}</td>
                          <td className="py-2 pr-3 font-bold text-[#76010d]">₹{Number(row.revenue).toFixed(2)}</td>
                          <td className="py-2 text-right">
                            <Badge tone={row.is_available ? "green" : "amber"}>{row.is_available ? "Available" : "Unavailable"}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {detailTab === "inventory" && (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className={`border-b text-[11px] uppercase ${isDark ? "border-slate-800 text-slate-400" : "border-slate-200 text-slate-500"}`}>
                        <th className="py-2 pr-3">Ingredient</th>
                        <th className="py-2 pr-3">Consumed</th>
                        <th className="py-2 pr-3">Restocked</th>
                        <th className="py-2 pr-3">Wasted</th>
                        <th className="py-2 pr-3">Current Stock</th>
                        <th className="py-2 pr-3">Reorder Level</th>
                        <th className="py-2 text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y ${isDark ? "divide-slate-800" : "divide-slate-100"}`}>
                      {(detailData?.items || []).map((row: any) => (
                        <tr key={row.inventory_item_id}>
                          <td className={`py-2 pr-3 font-bold ${headingText}`}>{row.ingredient_name}</td>
                          <td className="py-2 pr-3">
                            {row.consumed_quantity} {row.unit}
                          </td>
                          <td className="py-2 pr-3 text-emerald-600">
                            +{row.restocked_quantity} {row.unit}
                          </td>
                          <td className="py-2 pr-3 text-amber-600">
                            {row.wastage_quantity} {row.unit}
                          </td>
                          <td className="py-2 pr-3 font-bold">
                            {row.current_quantity} {row.unit}
                          </td>
                          <td className="py-2 pr-3">
                            {row.reorder_level} {row.unit}
                          </td>
                          <td className="py-2 text-right">
                            <Badge tone={row.is_low_stock ? "red" : "green"}>{row.is_low_stock ? "LOW STOCK" : "Healthy"}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {(!detailData?.items || detailData.items.length === 0) && (
                  <div className={`py-8 text-center text-xs ${mutedText}`}>
                    No detail rows match the current filter.
                  </div>
                )}
              </div>
            )}

            {/* Pagination */}
            <div className={`flex items-center justify-between border-t pt-3 text-xs ${isDark ? "border-slate-800 text-slate-400" : "border-slate-100 text-slate-600"}`}>
              <span>
                Page <strong>{detailData?.page ?? page}</strong> of <strong>{detailData?.total_pages ?? 1}</strong> • Total{" "}
                <strong>{detailData?.total ?? 0}</strong> records
              </span>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page >= (detailData?.total_pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    );
  }
);
BiAnalyticsPanel.displayName = "BiAnalyticsPanel";
