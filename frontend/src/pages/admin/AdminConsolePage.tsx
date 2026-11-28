import React, { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { PromotionsTab, SystemTab } from "./components/PromotionsSystemTab";
import { OrdersUsersTab } from "./components/OrdersUsersTab";
import { WebsiteQrTab } from "./components/WebsiteQrTab";

const BiAnalyticsPanel = lazy(() =>
  import("./components/BiAnalyticsPanel").then((m) => ({ default: m.BiAnalyticsPanel }))
);
const BackupRecoveryPanel = lazy(() =>
  import("./components/BackupRecoveryPanel").then((m) => ({ default: m.BackupRecoveryPanel }))
);
const ReconciliationPanel = lazy(() =>
  import("./components/ReconciliationPanel").then((m) => ({ default: m.ReconciliationPanel }))
);
const SecurityMonitorPanel = lazy(() =>
  import("./components/SecurityMonitorPanel").then((m) => ({ default: m.SecurityMonitorPanel }))
);
const OperationsControlCenterPanel = lazy(() =>
  import("./components/OperationsControlCenterPanel").then((m) => ({ default: m.OperationsControlCenterPanel }))
);
const MealPlansEventsInvoicesTab = lazy(() =>
  import("./components/MealPlansEventsInvoicesTab").then((m) => ({ default: m.MealPlansEventsInvoicesTab }))
);
const ForecastingAssistantTab = lazy(() =>
  import("./components/ForecastingAssistantTab").then((m) => ({ default: m.ForecastingAssistantTab }))
);
const KitchenPrinterDashboardTab = lazy(() =>
  import("../kitchen/components/KitchenPrinterDashboardTab").then((m) => ({ default: m.KitchenPrinterDashboardTab }))
);

const AdminPanelFallback = () => (
  <Card className="p-6 text-center text-xs text-slate-500">Loading operations module...</Card>
);

export const AdminConsolePage: React.FC = () => {
  const { pushToast } = useToast();
  const { user, selectedCanteenId } = useAppStore();
  const isCollegeAdmin = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));
  const offlinePendingCount = useOfflineStore(
    (s) => s.pendingQueue.filter((q) => q.status === "pending" || q.status === "conflict").length
  );
  const [tab, setTab] = useState<
    | "control_center"
    | "analytics"
    | "ai_forecast_assistant"
    | "orders"
    | "meal_events_invoices"
    | "locations"
    | "menu"
    | "qr"
    | "website_qr"
    | "queue"
    | "staff"
    | "promotions"
    | "support"
    | "reconciliation"
    | "security"
    | "backup"
    | "printers"
    | "network"
    | "system"
  >("analytics");

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
  const activeCanteenId = (!isCollegeAdmin && user?.assigned_canteen_id) ? user.assigned_canteen_id : (canteenId || canteens[0]?.id || "");
  const [scopeReportToCanteen, setScopeReportToCanteen] = useState(!isCollegeAdmin);
  const [reportPreset, setReportPreset] = useState("last_30_days");
  const [reportStartDate, setReportStartDate] = useState("");
  const [reportEndDate, setReportEndDate] = useState("");
  const [reportCategoryId, setReportCategoryId] = useState("");
  const [reportFoodItemId, setReportFoodItemId] = useState("");
  const [reportComparePrevious, setReportComparePrevious] = useState(true);
  const [expandedTicketId, setExpandedTicketId] = useState<string | null>(null);
  const [ticketThreadMap, setTicketThreadMap] = useState<Record<string, any[]>>({});

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
  const adminRealtimeActive = Boolean(
    user && (tab === "control_center" || tab === "analytics" || tab === "orders" || tab === "queue")
  );
  const { status: adminSyncStatus, lastSyncedAt: adminLastSyncedAt, triggerSync: triggerAdminSync } = useRealtimeSync({
    enabled: adminRealtimeActive,
    ssePath: `/realtime/staff/orders/stream${streamCanteenScope ? `?canteen_id=${streamCanteenScope}` : ""}`,
    wsPath: activeCanteenId ? `/ws/kitchen/${activeCanteenId}` : "/ws/board/all",
    queryKeys: [["admin-report"], ["admin-queue"], ["admin-all-orders"]],
  });

  const { data: report, isLoading: reportLoading, isError: reportError, isFetching: reportFetching, refetch: refetchReport } = useQuery<any>({
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
    enabled: tab === "analytics",
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/reports/dashboard${reportQueryCanteen}`)).data,
    refetchInterval: adminSyncStatus === "live" ? 60000 : 20000,
    refetchIntervalInBackground: false,
  });

  const { data: menuItems = [], refetch: refetchMenu } = useQuery<FoodItem[]>({
    queryKey: ["admin-menu", activeCanteenId],
    enabled: Boolean(activeCanteenId && (tab === "menu" || tab === "meal_events_invoices" || tab === "analytics")),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/items?include_inactive=true`)).data,
  });

  const { data: categories = [], refetch: refetchCategories } = useQuery<any[]>({
    queryKey: ["admin-cats", activeCanteenId],
    enabled: Boolean(activeCanteenId && (tab === "menu" || tab === "analytics")),
    queryFn: async () => (await api.get(`/menus/canteens/${activeCanteenId}/categories?include_inactive=true`)).data,
  });

  const { data: locationQrs = [], refetch: refetchQrs } = useQuery<any[]>({
    queryKey: ["admin-qrs", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "qr"),
    queryFn: async () => (await api.get(`/qr/locations?canteen_id=${activeCanteenId}`)).data,
  });

  const { data: queueDash, refetch: refetchQueue } = useQuery<any>({
    queryKey: ["admin-queue", activeCanteenId],
    enabled: Boolean(activeCanteenId && tab === "queue"),
    queryFn: async () => (await api.get(`/queue/canteens/${activeCanteenId}`)).data,
  });

  const { data: staffList = [], refetch: refetchStaff } = useQuery<any[]>({
    queryKey: ["admin-staff", activeCanteenId],
    enabled: tab === "staff" || tab === "support",
    queryFn: async () => (await api.get(`/staff${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: tickets = [], refetch: refetchTickets } = useQuery<any[]>({
    queryKey: ["admin-tickets", activeCanteenId],
    enabled: tab === "support",
    queryFn: async () => (await api.get(`/support/tickets${!isCollegeAdmin && activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });

  const { data: auditLogs = [] } = useQuery<any[]>({
    queryKey: ["admin-audits"],
    enabled: tab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/audit-logs?limit=40")).data,
  });

  const { data: health } = useQuery<any>({
    queryKey: ["admin-health"],
    enabled: tab === "system" && isCollegeAdmin,
    queryFn: async () => (await api.get("/admin/health")).data,
  });

  const [replyByTicket, setReplyByTicket] = useState<Record<string, string>>({});

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

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-[#380106] p-4 text-white">
        <div className="flex items-center gap-3">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-extrabold">CollegeBites Operations &amp; Admin Console</h1>
              <RealtimeStatusBadge status={adminSyncStatus} lastSyncedAt={adminLastSyncedAt} darkSurface />
            </div>
            <p className="text-xs text-[#fdedce]/80">{college?.college_name} • Real-time database analytics &amp; controls</p>
          </div>
        </div>
        <Select
          value={activeCanteenId}
          disabled={!isCollegeAdmin && Boolean(user?.assigned_canteen_id)}
          onChange={(e) => setCanteenId(e.target.value)}
          className="w-56 bg-slate-800 border-slate-700 text-white"
        >
          {canteens.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="no-print flex flex-wrap gap-2">
        {[
          { k: "analytics", l: "Business Analytics & Insights" },
          { k: "control_center", l: "Control Center" },
          { k: "ai_forecast_assistant", l: "AI Forecasting & Assistant" },
          { k: "orders", l: "Orders & Users" },
          { k: "printers", l: "Kitchen Printers" },
          { k: "meal_events_invoices", l: "Meal Plans, Events & Invoices" },
          { k: "locations", l: "Locations, Counters & Hours" },
          { k: "menu", l: "Menus & CSV" },
          { k: "qr", l: "Location QR Codes" },
          ...(isCollegeAdmin ? [{ k: "website_qr", l: "Website QR Generator" }] : []),
          { k: "queue", l: "Queue, Crowd & Slots" },
          { k: "staff", l: "Staff, Attendance & Tasks" },
          { k: "promotions", l: "Banners & Announcements" },
          { k: "support", l: "Support Tickets" },
          { k: "reconciliation", l: "Reconciliation" },
          { k: "security", l: "Security & Fraud" },
          ...(isCollegeAdmin ? [{ k: "backup", l: "Backups & DR" }] : []),
          { k: "network", l: offlinePendingCount > 0 ? `Network & Sync (${offlinePendingCount})` : "Network & Sync" },
          ...(isCollegeAdmin ? [{ k: "system", l: "Settings & Audits" }] : []),
        ].map((item) => (
          <Button
            key={item.k}
            size="sm"
            variant={tab === item.k ? "secondary" : "outline"}
            onClick={() => setTab(item.k as any)}
          >
            {item.l}
          </Button>
        ))}
      </div>

      {tab === "control_center" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <OperationsControlCenterPanel activeCanteenId={activeCanteenId} isCollegeAdmin={isCollegeAdmin} />
        </Suspense>
      )}

      {tab === "meal_events_invoices" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <MealPlansEventsInvoicesTab
            activeCanteenId={activeCanteenId}
            menuItems={menuItems}
            downloadBlob={downloadBlob}
          />
        </Suspense>
      )}

      {tab === "analytics" && reportLoading && !report && (
        <Card className="space-y-3 p-6">
          <div className="h-6 w-64 animate-pulse rounded bg-slate-200" />
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
            <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
            <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
            <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
          </div>
          <div className="h-56 animate-pulse rounded-xl bg-slate-100" />
        </Card>
      )}
      {tab === "analytics" && reportError && !report && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-red-200 bg-red-50 p-4 text-xs text-red-700">
          <span>Failed to load verified Enterprise BI analytics report. Please retry.</span>
          <Button variant="secondary" onClick={() => void refetchReport()}>
            Retry Analytics Load
          </Button>
        </Card>
      )}
      {tab === "analytics" && report && (
        <Suspense fallback={<AdminPanelFallback />}>
          <BiAnalyticsPanel
            report={report}
            isCollegeAdmin={isCollegeAdmin}
            scopeReportToCanteen={scopeReportToCanteen}
            setScopeReportToCanteen={setScopeReportToCanteen}
            reportPreset={reportPreset}
            setReportPreset={setReportPreset}
            reportStartDate={reportStartDate}
            setReportStartDate={setReportStartDate}
            reportEndDate={reportEndDate}
            setReportEndDate={setReportEndDate}
            reportCategoryId={reportCategoryId}
            setReportCategoryId={setReportCategoryId}
            reportFoodItemId={reportFoodItemId}
            setReportFoodItemId={setReportFoodItemId}
            reportComparePrevious={reportComparePrevious}
            setReportComparePrevious={setReportComparePrevious}
            categories={categories}
            menuItems={menuItems}
            reportQueryCanteen={reportQueryCanteen}
            downloadBlob={downloadBlob}
            onRefreshReport={() => void refetchReport()}
            refreshing={reportFetching}
          />
        </Suspense>
      )}
      {tab === "printers" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <KitchenPrinterDashboardTab activeCanteenId={activeCanteenId} />
        </Suspense>
      )}

      {tab === "ai_forecast_assistant" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <ForecastingAssistantTab activeCanteenId={activeCanteenId} canTrainForecast canViewForecast canViewAudit />
        </Suspense>
      )}

      {tab === "orders" && (
        <OrdersUsersTab
          activeCanteenId={activeCanteenId}
          syncStatus={adminSyncStatus}
          lastSyncedAt={adminLastSyncedAt}
          triggerSync={triggerAdminSync}
        />
      )}

      {tab === "locations" && (
        <LocationsTab canteens={canteens} activeCanteenId={activeCanteenId} refetchCanteens={refetchCanteens} />
      )}

      {tab === "menu" && (
        <MenuTab
          activeCanteenId={activeCanteenId}
          menuItems={menuItems}
          categories={categories}
          refetchMenu={refetchMenu}
          refetchCategories={refetchCategories}
          downloadBlob={downloadBlob}
        />
      )}

      {tab === "qr" && <QRTab activeCanteenId={activeCanteenId} locationQrs={locationQrs} refetchQrs={refetchQrs} />}

      {tab === "website_qr" && isCollegeAdmin && (
        <WebsiteQrTab canteens={canteens} defaultCanteenId={activeCanteenId} downloadBlob={downloadBlob} />
      )}

      {tab === "queue" && <QueueTab activeCanteenId={activeCanteenId} queueDash={queueDash} refetchQueue={refetchQueue} />}

      {tab === "staff" && <StaffTab activeCanteenId={activeCanteenId} staffList={staffList} refetchStaff={refetchStaff} />}

      {tab === "promotions" && <PromotionsTab activeCanteenId={activeCanteenId} />}

      {tab === "support" && (
        <Card className="p-5 space-y-3">
          <h2 className="font-bold text-slate-900">Customer Support Tickets ({tickets.length})</h2>
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
        </Card>
      )}

      {tab === "reconciliation" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <ReconciliationPanel isCollegeAdmin={isCollegeAdmin} activeCanteenId={activeCanteenId} downloadBlob={downloadBlob} />
        </Suspense>
      )}

      {tab === "security" && (
        <Suspense fallback={<AdminPanelFallback />}>
          <SecurityMonitorPanel isCollegeAdmin={isCollegeAdmin} activeCanteenId={activeCanteenId} />
        </Suspense>
      )}

      {tab === "backup" && isCollegeAdmin && (
        <Suspense fallback={<AdminPanelFallback />}>
          <BackupRecoveryPanel downloadBlob={downloadBlob} />
        </Suspense>
      )}

      {tab === "network" && <NetworkSyncPanel />}

      {tab === "system" && (
        <SystemTab college={college} refetchCollege={refetchCollege} health={health} auditLogs={auditLogs} />
      )}
    </div>
  );
};
