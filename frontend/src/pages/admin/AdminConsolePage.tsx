import React, { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bell,
  Boxes,
  Calendar,
  ChefHat,
  ChevronDown,
  ClipboardList,
  CreditCard,
  DollarSign,
  FileBarChart2,
  FolderTree,
  History,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Store,
  User as UserIcon,
  Users,
  UtensilsCrossed,
  X,
  Zap,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import type { Canteen, CollegeSettings, FoodItem } from "../../types";
import { BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Select, useToast } from "../../components/ui/Primitives";
import { NetworkSyncPanel } from "../../components/ui/NetworkSyncPanel";
import { RealtimeStatusBadge } from "../../components/ui/RealtimeStatusBadge";
import { LocationsTab } from "./components/LocationsTab";
import { MenuTab, QRTab } from "./components/MenuQrTab";
import { QueueTab, StaffTab } from "./components/QueueStaffTab";
import { SystemTab } from "./components/PromotionsSystemTab";
import { OrdersUsersTab } from "./components/OrdersUsersTab";
import { WebsiteQrTab } from "./components/WebsiteQrTab";
import { type AdminSectionId, DATE_PRESETS, formatPresetLabel } from "./components/v2/adminTheme";
import { AdminV2Overview } from "./components/v2/AdminV2Overview";
import { AdminV2FinanceView } from "./components/v2/AdminV2FinanceView";
import { AdminV2PaymentsView } from "./components/v2/AdminV2PaymentsView";
import { AdminV2CustomersView } from "./components/v2/AdminV2CustomersView";
import { AdminV2AnalyticsInsightsView } from "./components/v2/AdminV2AnalyticsInsightsView";
import { AdminV2ReportsView } from "./components/v2/AdminV2ReportsView";
import { AdminV2CategoriesView } from "./components/v2/AdminV2CategoriesView";
import { AdminV2InventoryView } from "./components/v2/AdminV2InventoryView";
import { AdminV2NotificationsView } from "./components/v2/AdminV2NotificationsView";
import { AdminV2OrderHistoryView } from "./components/v2/AdminV2OrderHistoryView";

const BackupRecoveryPanel = lazy(() =>
  import("./components/BackupRecoveryPanel").then((m) => ({ default: m.BackupRecoveryPanel }))
);
const SecurityMonitorPanel = lazy(() =>
  import("./components/SecurityMonitorPanel").then((m) => ({ default: m.SecurityMonitorPanel }))
);
const OperationsControlCenterPanel = lazy(() =>
  import("./components/OperationsControlCenterPanel").then((m) => ({ default: m.OperationsControlCenterPanel }))
);
const KitchenPrinterDashboardTab = lazy(() =>
  import("../kitchen/components/KitchenPrinterDashboardTab").then((m) => ({ default: m.KitchenPrinterDashboardTab }))
);

const AdminPanelFallback = () => (
  <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
    Loading workspace module...
  </div>
);

interface SidebarNavItem {
  id: AdminSectionId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group: "Core" | "Operations" | "Financial & BI" | "Administration";
}

const SIDEBAR_ITEMS: SidebarNavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, group: "Core" },
  { id: "live_orders", label: "Live Orders", icon: Activity, group: "Core" },
  { id: "order_history", label: "Order History", icon: History, group: "Core" },
  { id: "menu", label: "Food & Menu", icon: UtensilsCrossed, group: "Operations" },
  { id: "categories", label: "Categories", icon: FolderTree, group: "Operations" },
  { id: "inventory", label: "Inventory", icon: Boxes, group: "Operations" },
  { id: "kitchen", label: "Kitchen Management", icon: ChefHat, group: "Operations" },
  { id: "customers", label: "Customers", icon: Users, group: "Financial & BI" },
  { id: "payments", label: "Payments & Txns", icon: CreditCard, group: "Financial & BI" },
  { id: "finance", label: "Finance & Revenue", icon: DollarSign, group: "Financial & BI" },
  { id: "analytics_insights", label: "Analytics & Insights", icon: BarChart3, group: "Financial & BI" },
  { id: "reports", label: "Reports", icon: FileBarChart2, group: "Financial & BI" },
  { id: "notifications", label: "Notifications", icon: Bell, group: "Administration" },
  { id: "settings", label: "Settings", icon: Settings, group: "Administration" },
];

export const AdminConsolePage: React.FC = () => {
  const { pushToast } = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, logout, selectedCanteenId } = useAppStore();
  const isCollegeAdmin = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));
  const offlinePendingCount = useOfflineStore(
    (s) => s.pendingQueue.filter((q) => q.status === "pending" || q.status === "conflict").length
  );

  const [section, setSection] = useState<AdminSectionId>("overview");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Section-specific preserved sub-tabs
  const [liveOrdersSubTab, setLiveOrdersSubTab] = useState<"queue" | "control_center" | "support">("queue");
  const [kitchenSubTab, setKitchenSubTab] = useState<"queue" | "printers" | "staff" | "locations" | "qrs">("queue");
  const [settingsSubTab, setSettingsSubTab] = useState<"system" | "security" | "backup" | "network">("system");

  // Global Topbar Controls
  const [quickSearch, setQuickSearch] = useState("");
  const [quickMenuOpen, setQuickMenuOpen] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [clockLabel, setClockLabel] = useState(() =>
    new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })
  );
  const quickMenuRef = useRef<HTMLDivElement | null>(null);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const id = setInterval(() => {
      setClockLabel(
        new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })
      );
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (quickMenuRef.current && !quickMenuRef.current.contains(e.target as Node)) setQuickMenuOpen(false);
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) setProfileMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const { data: college, refetch: refetchCollege } = useQuery<CollegeSettings>({
    queryKey: ["college-settings"],
    staleTime: 300_000,
    queryFn: async () => (await api.get("/canteens/college")).data,
  });

  const { data: canteens = [], refetch: refetchCanteens } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    staleTime: 60_000,
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const [canteenId, setCanteenId] = useState(user?.assigned_canteen_id || selectedCanteenId || "");
  const activeCanteenId =
    !isCollegeAdmin && user?.assigned_canteen_id
      ? user.assigned_canteen_id
      : canteenId || canteens[0]?.id || "";
  const activeCanteenObj = canteens.find((c) => c.id === activeCanteenId);

  const [scopeReportToCanteen, setScopeReportToCanteen] = useState(!isCollegeAdmin);
  const [reportPreset, setReportPreset] = useState("last_30_days");
  const [reportStartDate, setReportStartDate] = useState("");
  const [reportEndDate, setReportEndDate] = useState("");
  const [reportCategoryId, setReportCategoryId] = useState("");
  const [reportFoodItemId, setReportFoodItemId] = useState("");
  const [reportComparePrevious, setReportComparePrevious] = useState(true);

  const [expandedTicketId, setExpandedTicketId] = useState<string | null>(null);
  const [ticketThreadMap, setTicketThreadMap] = useState<Record<string, any[]>>({});
  const [replyByTicket, setReplyByTicket] = useState<Record<string, string>>({});

  const reportParams = new URLSearchParams();
  if (scopeReportToCanteen && activeCanteenId) reportParams.set("canteen_id", activeCanteenId);
  if (reportPreset && reportPreset !== "custom") reportParams.set("preset", reportPreset);
  if (reportStartDate) reportParams.set("start_date", reportStartDate);
  if (reportEndDate) reportParams.set("end_date", reportEndDate);
  if (reportCategoryId) reportParams.set("category_id", reportCategoryId);
  if (reportFoodItemId) reportParams.set("food_item_id", reportFoodItemId);
  if (reportComparePrevious) reportParams.set("compare_previous", "true");
  const reportQueryCanteen = reportParams.toString() ? `?${reportParams.toString()}` : "";

  const streamCanteenScope =
    !isCollegeAdmin && user?.assigned_canteen_id
      ? user.assigned_canteen_id
      : scopeReportToCanteen && activeCanteenId
      ? activeCanteenId
      : "";

  const needsReportData = [
    "overview",
    "finance",
    "payments",
    "analytics_insights",
    "reports",
    "categories",
    "inventory",
    "customers",
    "order_history",
  ].includes(section);

  const { status: adminSyncStatus, lastSyncedAt: adminLastSyncedAt, triggerSync: triggerAdminSync } = useRealtimeSync({
    enabled: Boolean(user),
    ssePath: `/realtime/staff/orders/stream${streamCanteenScope ? `?canteen_id=${streamCanteenScope}` : ""}`,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : "/ws/board/all",
    queryKeys: [["admin-report"], ["admin-queue"], ["admin-all-orders"]],
  });

  const {
    data: report,
    isLoading: reportLoading,
    isError: reportError,
    isFetching: reportFetching,
    refetch: refetchReport,
  } = useQuery<any>({
    queryKey: [
      "admin-report",
      activeCanteenId,
      scopeReportToCanteen,
      reportPreset,
      reportStartDate,
      reportEndDate,
      reportCategoryId,
      reportFoodItemId,
      reportComparePrevious,
    ],
    enabled: needsReportData,
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/reports/dashboard${reportQueryCanteen}`)).data,
    refetchInterval: adminSyncStatus === "live" ? 60000 : 25000,
    refetchIntervalInBackground: false,
  });

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<FoodItem[]>({
    queryKey: ["admin-menu", activeCanteenId],
    enabled: Boolean(
      activeCanteenId && (section === "menu" || section === "categories" || section === "finance" || section === "analytics_insights")
    ),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?include_inactive=true`)).data,
  });

  const { data: categories = [], refetch: refetchCategories } = useQuery<any[]>({
    queryKey: ["admin-cats", activeCanteenId],
    enabled: Boolean(
      activeCanteenId && (section === "menu" || section === "categories" || section === "analytics_insights")
    ),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/categories?include_inactive=true`)).data,
  });

  const { data: locationQrs = [], refetch: refetchQrs } = useQuery<any[]>({
    queryKey: ["admin-qrs", activeCanteenId],
    enabled: Boolean(activeCanteenId && section === "kitchen" && kitchenSubTab === "qrs"),
    queryFn: async () => (await api.get(`/qr/locations?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: queueDash, refetch: refetchQueue } = useQuery<any>({
    queryKey: ["admin-queue", activeCanteenId],
    enabled: Boolean(activeCanteenId && section === "kitchen" && kitchenSubTab === "queue"),
    queryFn: async () => (await api.get(`/queue/canteens/${activeCanteenId}`)).data,
  });

  const { data: staffList = [], refetch: refetchStaff } = useQuery<any[]>({
    queryKey: ["admin-staff", activeCanteenId],
    enabled: (section === "kitchen" && kitchenSubTab === "staff") || (section === "live_orders" && liveOrdersSubTab === "support"),
    queryFn: async () => (await api.get(`/staff${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: tickets = [], refetch: refetchTickets } = useQuery<any[]>({
    queryKey: ["admin-tickets", activeCanteenId],
    enabled: section === "live_orders" && liveOrdersSubTab === "support",
    queryFn: async () =>
      (await api.get(`/support/tickets${!isCollegeAdmin && activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: notifications = [] } = useQuery<any[]>({
    queryKey: ["notifications-my"],
    enabled: Boolean(user),
    staleTime: 30_000,
    queryFn: async () => (await api.get("/notifications/my")).data,
  });
  const unreadNotifCount = notifications.filter((n: any) => !n.is_read).length;

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["admin-audits"],
    enabled: section === "settings" && settingsSubTab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/audit-logs?limit=40")).data,
  });

  const { data: health } = useQuery<any>({
    queryKey: ["admin-health"],
    enabled: section === "settings" && settingsSubTab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/health")).data,
  });

  const downloadBlob = async (url: string, filename: string) => {
    try {
      const res = await api.get(url, { responseType: "blob" });
      const objUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(objUrl);
    } catch (err) {
      pushToast(getApiError(err, "Export failed"), "error");
    }
  };

  const handleGlobalSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = quickSearch.trim().toLowerCase();
    if (!q) return;
    if (q.includes("pay") || q.includes("rzp") || q.includes("txn") || q.includes("upi")) {
      setSection("payments");
    } else if (q.includes("menu") || q.includes("dish") || q.includes("food") || q.includes("dosa")) {
      setSection("menu");
    } else if (q.includes("inv") || q.includes("stock")) {
      setSection("inventory");
    } else if (q.includes("cust") || q.includes("user")) {
      setSection("customers");
    } else if (q.includes("rep") || q.includes("pdf") || q.includes("csv")) {
      setSection("reports");
    } else {
      setSection("order_history");
    }
  };

  const handleRefreshAll = () => {
    triggerAdminSync();
    void refetchReport();
    qc.invalidateQueries({ queryKey: ["bi-v2-order-history"] });
    qc.invalidateQueries({ queryKey: ["admin-payments-ledger"] });
    pushToast("Dashboard synced with latest PostgreSQL metrics", "info");
  };

  const currentNavItem = SIDEBAR_ITEMS.find((i) => i.id === section) || SIDEBAR_ITEMS[0];
  const scopeLabel =
    scopeReportToCanteen && activeCanteenObj ? activeCanteenObj.name : isCollegeAdmin ? "All Campus Canteens" : activeCanteenObj?.name || "Canteen";

  const renderSidebarNav = (isMobileDrawer = false) => {
    const groups: ("Core" | "Operations" | "Financial & BI" | "Administration")[] = [
      "Core",
      "Operations",
      "Financial & BI",
      "Administration",
    ];
    return (
      <div className="flex h-full flex-col justify-between bg-[#0B1929] text-[#F4F8FC]">
        <div className="space-y-4 p-3 overflow-y-auto">
          {/* Sidebar Brand Row */}
          <div className="flex items-center justify-between gap-2 px-1 py-1.5">
            <Link to="/" className="flex items-center gap-2.5 min-w-0">
              <BrandLogo size="sm" variant="dark" />
              {(!sidebarCollapsed || isMobileDrawer) && (
                <div className="min-w-0">
                  <div className="text-sm font-black tracking-tight text-[#F4F8FC] truncate">CollegeBites</div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-[#20C5D8] truncate">
                    Administrator Portal
                  </div>
                </div>
              )}
            </Link>
            {isMobileDrawer ? (
              <button
                type="button"
                onClick={() => setMobileMenuOpen(false)}
                className="rounded-lg p-1.5 text-[#9BAFC2] hover:bg-[#153149] hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setSidebarCollapsed((c) => !c)}
                title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                className="hidden lg:inline-flex rounded-lg p-1.5 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#20C5D8]"
              >
                {sidebarCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
              </button>
            )}
          </div>

          {/* 14-Item Sidebar Navigation */}
          <nav aria-label="Admin Portal Navigation" className="space-y-4">
            {groups.map((grp) => {
              const items = SIDEBAR_ITEMS.filter((it) => it.group === grp);
              return (
                <div key={grp} className="space-y-1">
                  {(!sidebarCollapsed || isMobileDrawer) && (
                    <div className="px-3 pb-1 text-[10px] font-bold uppercase tracking-widest text-[#9BAFC2]/70">
                      {grp}
                    </div>
                  )}
                  {items.map((item) => {
                    const Icon = item.icon;
                    const active = section === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          setSection(item.id);
                          if (isMobileDrawer) setMobileMenuOpen(false);
                        }}
                        title={item.label}
                        className={`relative flex w-full items-center gap-3 rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
                          active
                            ? "bg-[#153149] text-[#20C5D8] shadow-sm"
                            : "text-[#9BAFC2] hover:bg-[#102438] hover:text-[#F4F8FC]"
                        }`}
                      >
                        {active && (
                          <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r-full bg-[#20C5D8]" />
                        )}
                        <Icon className={`h-4 w-4 shrink-0 ${active ? "text-[#20C5D8]" : "text-[#9BAFC2]"}`} />
                        {(!sidebarCollapsed || isMobileDrawer) && (
                          <span className="truncate flex-1 text-left">{item.label}</span>
                        )}
                        {item.id === "notifications" && unreadNotifCount > 0 && (!sidebarCollapsed || isMobileDrawer) && (
                          <span className="rounded-full bg-[#20C5D8] px-1.5 py-0.5 text-[10px] font-black text-[#071321]">
                            {unreadNotifCount}
                          </span>
                        )}
                        {item.id === "settings" && offlinePendingCount > 0 && (!sidebarCollapsed || isMobileDrawer) && (
                          <span className="rounded-full bg-[#F5B942] px-1.5 py-0.5 text-[10px] font-black text-[#071321]">
                            {offlinePendingCount}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </nav>
        </div>

        {/* Bottom Campus Status Footer */}
        <div className="border-t border-[#368BEA]/15 p-3 space-y-2">
          {(!sidebarCollapsed || isMobileDrawer) && (
            <div className="rounded-xl border border-[#368BEA]/20 bg-[#102438] p-2.5 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-[#9BAFC2] truncate">{college?.college_name || "CollegeBites"}</span>
                <span className="h-2 w-2 rounded-full bg-[#22C58B]" title="Online" />
              </div>
              <div className="mt-1 font-bold text-[#F4F8FC] truncate">{activeCanteenObj?.name || "Campus Portal"}</div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <Link
              to="/"
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[#368BEA]/25 bg-[#102438] px-2.5 py-2 text-[11px] font-bold text-[#9BAFC2] hover:border-[#20C5D8]/50 hover:text-[#20C5D8]"
              title="Open Student Ordering Storefront"
            >
              <Store className="h-3.5 w-3.5 shrink-0" />
              {(!sidebarCollapsed || isMobileDrawer) && <span>Storefront</span>}
            </Link>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="cb-admin-v2 min-h-screen flex bg-[#071321] text-[#F4F8FC]">
      {/* Desktop Collapsible Sidebar */}
      <aside
        className={`no-print hidden lg:flex shrink-0 flex-col border-r border-[#368BEA]/20 bg-[#0B1929] transition-all duration-200 sticky top-0 h-screen ${
          sidebarCollapsed ? "w-[74px]" : "w-64"
        }`}
      >
        {renderSidebarNav(false)}
      </aside>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="no-print fixed inset-0 z-50 flex lg:hidden">
          <div className="fixed inset-0 bg-black/65 backdrop-blur-sm" onClick={() => setMobileMenuOpen(false)} />
          <div className="relative z-10 w-72 max-w-[85vw] border-r border-[#368BEA]/25 bg-[#0B1929] h-full">
            {renderSidebarNav(true)}
          </div>
        </div>
      )}

      {/* Main Content Shell */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Top Enterprise Navigation Header */}
        <header className="no-print sticky top-0 z-30 border-b border-[#368BEA]/20 bg-[#0B1929]/95 backdrop-blur-md px-4 py-3 sm:px-6 space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Left: Mobile drawer + Page title + Live Indicator */}
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(true)}
                className="inline-flex lg:hidden rounded-xl border border-[#368BEA]/25 bg-[#102438] p-2 text-[#F4F8FC]"
                aria-label="Open admin sidebar"
              >
                <Menu className="h-4 w-4" />
              </button>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm sm:text-base font-black tracking-tight text-[#F4F8FC] truncate">
                    {currentNavItem.label}
                  </span>
                  <RealtimeStatusBadge status={adminSyncStatus} lastSyncedAt={adminLastSyncedAt} darkSurface />
                </div>
              </div>
            </div>

            {/* Center: Search + Canteen Switcher + Clock */}
            <div className="flex flex-wrap items-center gap-2">
              <form onSubmit={handleGlobalSearchSubmit} className="relative hidden md:block">
                <Search className="h-3.5 w-3.5 text-[#9BAFC2] absolute left-3 top-2.5" />
                <input
                  type="text"
                  value={quickSearch}
                  onChange={(e) => setQuickSearch(e.target.value)}
                  placeholder="Jump to orders, menu, payments..."
                  className="h-9 w-56 rounded-xl border border-[#368BEA]/25 bg-[#102438] pl-8 pr-3 text-xs text-[#F4F8FC] placeholder:text-[#7c95ad] focus:border-[#20C5D8] focus:outline-none"
                />
              </form>

              <select
                value={activeCanteenId}
                disabled={!isCollegeAdmin && Boolean(user?.assigned_canteen_id)}
                onChange={(e) => setCanteenId(e.target.value)}
                aria-label="Select canteen"
                className="h-9 rounded-xl border border-[#368BEA]/25 bg-[#102438] px-3 text-xs font-semibold text-[#F4F8FC] focus:border-[#20C5D8] focus:outline-none"
              >
                {canteens.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>

              <div className="hidden xl:flex items-center gap-1.5 rounded-xl border border-[#368BEA]/20 bg-[#102438] px-3 h-9 text-[11px] font-mono text-[#9BAFC2]">
                <Calendar className="h-3.5 w-3.5 text-[#20C5D8]" />
                <span>{clockLabel} IST</span>
              </div>
            </div>

            {/* Right: Refresh + Quick Actions + Notifications + Profile */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRefreshAll}
                title="Refresh dashboard metrics"
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[#368BEA]/25 bg-[#102438] px-3 text-xs font-semibold text-[#F4F8FC] hover:border-[#20C5D8]/50 hover:text-[#20C5D8]"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${reportFetching ? "animate-spin text-[#20C5D8]" : ""}`} />
                <span className="hidden sm:inline">Refresh</span>
              </button>

              {/* Quick Actions Dropdown */}
              <div className="relative" ref={quickMenuRef}>
                <button
                  type="button"
                  onClick={() => setQuickMenuOpen((v) => !v)}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#20C5D8] px-3 text-xs font-extrabold text-[#071321] hover:bg-[#3ad4e6]"
                >
                  <Zap className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Quick Actions</span>
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
                {quickMenuOpen && (
                  <div className="absolute right-0 mt-2 w-56 rounded-2xl border border-[#20C5D8]/30 bg-[#0B1929] p-1.5 text-xs shadow-2xl z-50">
                    <button
                      type="button"
                      onClick={() => {
                        setSection("menu");
                        setQuickMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[#F4F8FC] hover:bg-[#153149]"
                    >
                      <Plus className="h-3.5 w-3.5 text-[#20C5D8]" /> Add / Manage Food Items
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setSection("payments");
                        setQuickMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[#F4F8FC] hover:bg-[#153149]"
                    >
                      <CreditCard className="h-3.5 w-3.5 text-[#22C58B]" /> Payments &amp; Reconciliation
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void downloadBlob(`/reports/export/pdf${reportQueryCanteen}`, "collegebites-report.pdf");
                        setQuickMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[#F4F8FC] hover:bg-[#153149]"
                    >
                      <FileBarChart2 className="h-3.5 w-3.5 text-[#368BEA]" /> Download Executive PDF
                    </button>
                    <div className="my-1 border-t border-[#368BEA]/20" />
                    <Link
                      to="/kitchen"
                      onClick={() => setQuickMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <ChefHat className="h-3.5 w-3.5" /> Live Kitchen Display (KDS)
                    </Link>
                    <Link
                      to="/cashier"
                      onClick={() => setQuickMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <ClipboardList className="h-3.5 w-3.5" /> Cashier Counter POS
                    </Link>
                    <Link
                      to="/inventory"
                      onClick={() => setQuickMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <Boxes className="h-3.5 w-3.5" /> Inventory Workspace
                    </Link>
                    <Link
                      to="/food-safety"
                      onClick={() => setQuickMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <ShieldCheck className="h-3.5 w-3.5" /> Food Safety Portal
                    </Link>
                  </div>
                )}
              </div>

              {/* Notification Center Bell */}
              <button
                type="button"
                onClick={() => setSection("notifications")}
                aria-label="Admin notifications"
                className="relative inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#368BEA]/25 bg-[#102438] text-[#9BAFC2] hover:border-[#20C5D8]/50 hover:text-[#20C5D8]"
              >
                <Bell className="h-4 w-4" />
                {unreadNotifCount > 0 && (
                  <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[#F06464] px-1 text-[10px] font-black text-white">
                    {unreadNotifCount > 9 ? "9+" : unreadNotifCount}
                  </span>
                )}
              </button>

              {/* Profile Menu */}
              <div className="relative" ref={profileMenuRef}>
                <button
                  type="button"
                  onClick={() => setProfileMenuOpen((v) => !v)}
                  className="inline-flex h-9 items-center gap-2 rounded-xl border border-[#368BEA]/25 bg-[#102438] px-2.5 text-xs font-bold text-[#F4F8FC] hover:border-[#20C5D8]/50"
                >
                  <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-[#20C5D8]/20 text-[#20C5D8]">
                    <UserIcon className="h-3.5 w-3.5" />
                  </div>
                  <span className="hidden md:inline max-w-[110px] truncate">{user?.full_name || "Admin"}</span>
                  <ChevronDown className="h-3.5 w-3.5 text-[#9BAFC2]" />
                </button>
                {profileMenuOpen && (
                  <div className="absolute right-0 mt-2 w-56 rounded-2xl border border-[#20C5D8]/30 bg-[#0B1929] p-2 text-xs shadow-2xl z-50 space-y-1">
                    <div className="px-2.5 py-1.5 border-b border-[#368BEA]/20">
                      <div className="font-bold text-[#F4F8FC] truncate">{user?.full_name}</div>
                      <div className="text-[10px] text-[#20C5D8] uppercase">{(user?.roles || []).join(" · ")}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setSection("settings");
                        setProfileMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <Settings className="h-3.5 w-3.5" /> Admin Settings
                    </button>
                    <Link
                      to="/profile"
                      onClick={() => setProfileMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    >
                      <UserIcon className="h-3.5 w-3.5" /> Account Profile
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        logout();
                        navigate("/login");
                      }}
                      className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-[#F06464] hover:bg-[#F06464]/15"
                    >
                      <LogOut className="h-3.5 w-3.5" /> Sign Out
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Analytics Filter Ribbon (Always Visible on Top for Seamless Period Switching) */}
          {needsReportData && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#368BEA]/15 pt-2 text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                {DATE_PRESETS.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    onClick={() => {
                      setReportPreset(p.key);
                      if (p.key !== "custom") {
                        setReportStartDate("");
                        setReportEndDate("");
                      }
                    }}
                    className={`rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                      reportPreset === p.key
                        ? "bg-[#20C5D8] text-[#071321]"
                        : "bg-[#102438] text-[#9BAFC2] hover:bg-[#153149] hover:text-[#F4F8FC]"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {isCollegeAdmin && (
                  <label className="flex items-center gap-1.5 text-[11px] font-semibold text-[#9BAFC2] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={scopeReportToCanteen}
                      onChange={(e) => setScopeReportToCanteen(e.target.checked)}
                    />
                    Selected Canteen Only
                  </label>
                )}
                <label className="flex items-center gap-1.5 text-[11px] font-semibold text-[#9BAFC2] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={reportComparePrevious}
                    onChange={(e) => setReportComparePrevious(e.target.checked)}
                  />
                  Compare prior
                </label>

                {reportPreset === "custom" && (
                  <div className="flex items-center gap-1.5">
                    <input
                      type="date"
                      value={reportStartDate}
                      onChange={(e) => setReportStartDate(e.target.value)}
                      className="rounded-lg border border-[#368BEA]/30 bg-[#102438] px-2 py-1 text-[11px] text-[#F4F8FC]"
                    />
                    <span className="text-[#9BAFC2]">→</span>
                    <input
                      type="date"
                      value={reportEndDate}
                      onChange={(e) => setReportEndDate(e.target.value)}
                      className="rounded-lg border border-[#368BEA]/30 bg-[#102438] px-2 py-1 text-[11px] text-[#F4F8FC]"
                    />
                  </div>
                )}

                {categories.length > 0 && (
                  <select
                    value={reportCategoryId}
                    onChange={(e) => {
                      setReportCategoryId(e.target.value);
                      setReportFoodItemId("");
                    }}
                    aria-label="Filter analytics by category"
                    className="rounded-lg border border-[#368BEA]/30 bg-[#102438] px-2 py-1 text-[11px] text-[#F4F8FC]"
                  >
                    <option value="">All Categories</option>
                    {categories.map((c: any) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}

                {menuItems.length > 0 && (
                  <select
                    value={reportFoodItemId}
                    onChange={(e) => setReportFoodItemId(e.target.value)}
                    aria-label="Filter analytics by dish"
                    className="rounded-lg border border-[#368BEA]/30 bg-[#102438] px-2 py-1 text-[11px] text-[#F4F8FC] max-w-[155px]"
                  >
                    <option value="">All Products</option>
                    {menuItems
                      .filter((m) => !reportCategoryId || m.category_id === reportCategoryId)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                  </select>
                )}
              </div>
            </div>
          )}
        </header>

        {/* Main Workspace Canvas */}
        <main className="flex-1 p-4 sm:p-6 max-w-[1600px] w-full mx-auto space-y-6">
          {/* Analytics Loading / Error Handling */}
          {needsReportData && reportLoading && !report && (
            <div className="space-y-4">
              <div className="h-28 animate-pulse rounded-2xl bg-[#102438]" />
              <div className="grid gap-3 sm:grid-cols-4">
                <div className="h-28 animate-pulse rounded-2xl bg-[#102438]" />
                <div className="h-28 animate-pulse rounded-2xl bg-[#102438]" />
                <div className="h-28 animate-pulse rounded-2xl bg-[#102438]" />
                <div className="h-28 animate-pulse rounded-2xl bg-[#102438]" />
              </div>
              <div className="h-64 animate-pulse rounded-2xl bg-[#102438]" />
            </div>
          )}

          {needsReportData && reportError && !report && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#F06464]/40 bg-[#F06464]/10 p-4 text-xs text-[#F4F8FC]">
              <span>Unable to load verified analytics from backend right now. Existing operations tabs remain functional.</span>
              <Button size="sm" variant="primary" onClick={() => void refetchReport()}>
                Retry Load
              </Button>
            </div>
          )}

          {/* 1. OVERVIEW */}
          {section === "overview" && report && (
            <AdminV2Overview
              report={report}
              preset={reportPreset}
              canteenName={scopeLabel}
              onNavigateSection={(sec) => setSection(sec)}
            />
          )}

          {/* 2. LIVE ORDERS */}
          {section === "live_orders" && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-extrabold text-[#F4F8FC]">Live Order Operations &amp; Control Center</h2>
                  <p className="text-xs text-[#9BAFC2]">
                    Accept incoming orders, update cooking progress, handle counter handovers, and monitor support tickets.
                  </p>
                </div>
                <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
                  {[
                    { k: "queue", l: "Live Order Queue" },
                    { k: "control_center", l: "Operations Control Center" },
                    { k: "support", l: `Support Tickets (${tickets.length})` },
                  ].map((t) => (
                    <button
                      key={t.k}
                      type="button"
                      onClick={() => setLiveOrdersSubTab(t.k as any)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                        liveOrdersSubTab === t.k ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                      }`}
                    >
                      {t.l}
                    </button>
                  ))}
                </div>
              </div>

              {liveOrdersSubTab === "queue" && (
                <OrdersUsersTab
                  activeCanteenId={activeCanteenId}
                  syncStatus={adminSyncStatus}
                  lastSyncedAt={adminLastSyncedAt}
                  triggerSync={triggerAdminSync}
                  sectionMode="orders"
                />
              )}

              {liveOrdersSubTab === "control_center" && (
                <Suspense fallback={<AdminPanelFallback />}>
                  <OperationsControlCenterPanel activeCanteenId={activeCanteenId} isCollegeAdmin={isCollegeAdmin} />
                </Suspense>
              )}

              {liveOrdersSubTab === "support" && (
                <Card className="p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <LifeBuoy className="h-4 w-4 text-[#20C5D8]" />
                    <h3 className="font-bold text-[#F4F8FC]">Customer Support Tickets ({tickets.length})</h3>
                  </div>
                  {tickets.map((t) => (
                    <div key={t.id} className="rounded-xl border border-slate-200 p-4 text-xs space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="font-bold text-sm">
                            {t.ticket_number} — {t.subject}
                          </div>
                          <div className="text-slate-500">
                            {t.category} • {t.description}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge tone={t.status === "resolved" ? "green" : "amber"}>{t.status}</Badge>
                          <Select
                            value={t.assigned_to_user_id || ""}
                            onChange={async (e) => {
                              if (!e.target.value) return;
                              try {
                                await api.post(`/support/tickets/${t.id}/assign`, { assigned_to_user_id: e.target.value });
                                pushToast("Ticket assigned", "success");
                                refetchTickets();
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                            className="w-40"
                          >
                            <option value="">Assign Staff...</option>
                            {staffList.map((s) => (
                              <option key={s.user_id} value={s.user_id}>
                                {s.full_name}
                              </option>
                            ))}
                          </Select>
                          {t.status !== "resolved" && t.status !== "closed" && (
                            <Button
                              size="sm"
                              variant="success"
                              onClick={async () => {
                                try {
                                  await api.post(`/support/tickets/${t.id}/resolve?resolution_note=Resolved%20by%20admin`);
                                  pushToast("Ticket marked resolved", "success");
                                  refetchTickets();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              Resolve
                            </Button>
                          )}
                          {t.status !== "closed" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={async () => {
                                try {
                                  await api.patch(`/support/tickets/${t.id}/status`, {
                                    status: "closed",
                                    note: "Closed by admin after verification",
                                  });
                                  pushToast("Ticket closed", "info");
                                  refetchTickets();
                                } catch (err) {
                                  pushToast(getApiError(err), "error");
                                }
                              }}
                            >
                              Close
                            </Button>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            if (expandedTicketId === t.id) {
                              setExpandedTicketId(null);
                              return;
                            }
                            try {
                              const msgs = (await api.get(`/support/tickets/${t.id}/messages`)).data;
                              setTicketThreadMap((p) => ({ ...p, [t.id]: msgs }));
                              setExpandedTicketId(t.id);
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          {expandedTicketId === t.id ? "Hide Thread" : "View Thread"}
                        </Button>
                        <Input
                          value={replyByTicket[t.id] || ""}
                          onChange={(e) => setReplyByTicket((p) => ({ ...p, [t.id]: e.target.value }))}
                          placeholder="Write response to customer..."
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            const msg = replyByTicket[t.id];
                            if (!msg?.trim()) return;
                            try {
                              await api.post(`/support/tickets/${t.id}/messages`, { message: msg });
                              setReplyByTicket((p) => ({ ...p, [t.id]: "" }));
                              const msgs = (await api.get(`/support/tickets/${t.id}/messages`)).data;
                              setTicketThreadMap((p) => ({ ...p, [t.id]: msgs }));
                              setExpandedTicketId(t.id);
                              pushToast("Reply sent", "success");
                              refetchTickets();
                            } catch (err) {
                              pushToast(getApiError(err), "error");
                            }
                          }}
                        >
                          Send Reply
                        </Button>
                      </div>
                      {expandedTicketId === t.id && (
                        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-1.5">
                          {(ticketThreadMap[t.id] || []).length === 0 ? (
                            <div className="text-slate-400">No messages in thread yet.</div>
                          ) : (
                            (ticketThreadMap[t.id] || []).map((m: any) => (
                              <div key={m.id} className="text-xs">
                                <span className="font-bold uppercase text-slate-700">{m.sender_role}:</span>{" "}
                                <span className="text-slate-700">{m.message}</span>{" "}
                                <span className="text-[10px] text-slate-400">{m.created_at?.slice(11, 16)}</span>
                              </div>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                  {tickets.length === 0 && (
                    <div className="py-8 text-center text-xs text-[#9BAFC2]">No support tickets in queue.</div>
                  )}
                </Card>
              )}
            </div>
          )}

          {/* 3. ORDER HISTORY */}
          {section === "order_history" && report && (
            <AdminV2OrderHistoryView
              report={report}
              preset={reportPreset}
              reportQueryCanteen={reportQueryCanteen}
            />
          )}

          {/* 4. FOOD & MENU MANAGEMENT */}
          {section === "menu" && (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-extrabold text-[#F4F8FC]">Food &amp; Menu Management</h2>
                <p className="text-xs text-[#9BAFC2]">
                  Add dishes, upload images, configure meal schedules, variants/add-ons, approve price requests, and run CSV imports.
                </p>
              </div>
              <MenuTab
                activeCanteenId={activeCanteenId}
                menuItems={menuItems}
                categories={categories}
                refetchMenu={refetchMenu}
                refetchCategories={refetchCategories}
                downloadBlob={downloadBlob}
              />
            </div>
          )}

          {/* 5. CATEGORIES */}
          {section === "categories" && (
            <AdminV2CategoriesView
              activeCanteenId={activeCanteenId}
              categories={categories}
              menuItems={menuItems}
              report={report}
              refetchCategories={refetchCategories}
              onOpenMenu={() => setSection("menu")}
            />
          )}

          {/* 6. INVENTORY */}
          {section === "inventory" && report && (
            <AdminV2InventoryView report={report} reportQueryCanteen={reportQueryCanteen} />
          )}

          {/* 7. KITCHEN MANAGEMENT */}
          {section === "kitchen" && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-extrabold text-[#F4F8FC]">Kitchen, Printers, Staff &amp; Counter Topology</h2>
                  <p className="text-xs text-[#9BAFC2]">
                    Manage live kitchen queues, automated thermal printers, staff rosters, counter operating hours, and QR codes.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
                  {[
                    { k: "queue", l: "Queue & Prep" },
                    { k: "printers", l: "Thermal Printers" },
                    { k: "staff", l: "Staff & Shifts" },
                    { k: "locations", l: "Counters & Hours" },
                    { k: "qrs", l: "Counter & Website QRs" },
                  ].map((t) => (
                    <button
                      key={t.k}
                      type="button"
                      onClick={() => setKitchenSubTab(t.k as any)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                        kitchenSubTab === t.k ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                      }`}
                    >
                      {t.l}
                    </button>
                  ))}
                </div>
              </div>

              {kitchenSubTab === "queue" && (
                <QueueTab activeCanteenId={activeCanteenId} queueDash={queueDash} refetchQueue={refetchQueue} />
              )}
              {kitchenSubTab === "printers" && (
                <Suspense fallback={<AdminPanelFallback />}>
                  <KitchenPrinterDashboardTab activeCanteenId={activeCanteenId} />
                </Suspense>
              )}
              {kitchenSubTab === "staff" && (
                <StaffTab activeCanteenId={activeCanteenId} staffList={staffList} refetchStaff={refetchStaff} />
              )}
              {kitchenSubTab === "locations" && (
                <LocationsTab canteens={canteens} activeCanteenId={activeCanteenId} refetchCanteens={refetchCanteens} />
              )}
              {kitchenSubTab === "qrs" && (
                <div className="space-y-6">
                  <QRTab activeCanteenId={activeCanteenId} locationQrs={locationQrs} refetchQrs={refetchQrs} />
                  {isCollegeAdmin && (
                    <WebsiteQrTab canteens={canteens} defaultCanteenId={activeCanteenId} downloadBlob={downloadBlob} />
                  )}
                </div>
              )}
            </div>
          )}

          {/* 8. CUSTOMERS */}
          {section === "customers" && report && (
            <AdminV2CustomersView
              report={report}
              activeCanteenId={activeCanteenId}
              syncStatus={adminSyncStatus}
              lastSyncedAt={adminLastSyncedAt}
              triggerSync={triggerAdminSync}
            />
          )}

          {/* 9. PAYMENTS & TRANSACTIONS */}
          {section === "payments" && report && (
            <AdminV2PaymentsView
              report={report}
              isCollegeAdmin={isCollegeAdmin}
              activeCanteenId={activeCanteenId}
              scopeToCanteen={scopeReportToCanteen}
              downloadBlob={downloadBlob}
            />
          )}

          {/* 10. FINANCE & REVENUE */}
          {section === "finance" && report && (
            <AdminV2FinanceView
              report={report}
              activeCanteenId={activeCanteenId}
              menuItems={menuItems}
              downloadBlob={downloadBlob}
              onNavigateSection={(sec) => setSection(sec)}
            />
          )}

          {/* 11. ANALYTICS & INSIGHTS */}
          {section === "analytics_insights" && report && (
            <AdminV2AnalyticsInsightsView
              report={report}
              activeCanteenId={activeCanteenId}
              onJumpToOrderDrilldown={() => setSection("order_history")}
            />
          )}

          {/* 12. REPORTS */}
          {section === "reports" && report && (
            <AdminV2ReportsView
              report={report}
              preset={reportPreset}
              reportQueryCanteen={reportQueryCanteen}
              downloadBlob={downloadBlob}
            />
          )}

          {/* 13. NOTIFICATIONS */}
          {section === "notifications" && <AdminV2NotificationsView activeCanteenId={activeCanteenId} />}

          {/* 14. SETTINGS */}
          {section === "settings" && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-extrabold text-[#F4F8FC]">Administration, Security, Backups &amp; System Settings</h2>
                  <p className="text-xs text-[#9BAFC2]">
                    Platform configuration, fraud monitoring, disaster recovery backups, and offline sync controls.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
                  {[
                    { k: "system", l: "College & System" },
                    { k: "security", l: "Security & Fraud" },
                    ...(isCollegeAdmin ? [{ k: "backup", l: "Backups & DR" }] : []),
                    {
                      k: "network",
                      l: offlinePendingCount > 0 ? `Network & Sync (${offlinePendingCount})` : "Network & Sync",
                    },
                  ].map((t) => (
                    <button
                      key={t.k}
                      type="button"
                      onClick={() => setSettingsSubTab(t.k as any)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                        settingsSubTab === t.k ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
                      }`}
                    >
                      {t.l}
                    </button>
                  ))}
                </div>
              </div>

              {settingsSubTab === "system" && (
                <SystemTab college={college} refetchCollege={refetchCollege} health={health} auditLogs={auditLogs} />
              )}
              {settingsSubTab === "security" && (
                <Suspense fallback={<AdminPanelFallback />}>
                  <SecurityMonitorPanel isCollegeAdmin={isCollegeAdmin} activeCanteenId={activeCanteenId} />
                </Suspense>
              )}
              {settingsSubTab === "backup" && isCollegeAdmin && (
                <Suspense fallback={<AdminPanelFallback />}>
                  <BackupRecoveryPanel downloadBlob={downloadBlob} />
                </Suspense>
              )}
              {settingsSubTab === "network" && <NetworkSyncPanel />}
            </div>
          )}

          {/* Subtle Audit Footer Inside Main Canvas */}
          <footer className="no-print border-t border-[#368BEA]/15 pt-4 pb-6 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#9BAFC2]">
            <span>
              {college?.college_name || "CollegeBites"} • Period: {formatPresetLabel(reportPreset, reportStartDate, reportEndDate)}
            </span>
            <span>Real-time PostgreSQL BI • Strict Razorpay Verified Ledger &amp; No-Refunds Policy</span>
          </footer>
        </main>
      </div>
    </div>
  );
};
