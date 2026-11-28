import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Megaphone, Monitor, Shield, Sparkles } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import type { CollegeSettings } from "../../../types";
import { Badge, Button, Card, Input, Select, useToast } from "../../../components/ui/Primitives";

export const PromotionsTab: React.FC<{ activeCanteenId: string }> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const { data: promos = [], refetch: refetchPromos } = useQuery<any[]>({
    queryKey: ["admin-promotions", activeCanteenId],
    queryFn: async () => (await api.get(`/promotions${activeCanteenId ? `?canteen_id=${activeCanteenId}` : ""}`)).data,
  });
  const { data: announcements = [], refetch: refetchAnn } = useQuery<any[]>({
    queryKey: ["admin-announcements"],
    queryFn: async () => (await api.get("/notifications/announcements")).data,
  });

  const [promoTitle, setPromoTitle] = useState("");
  const [promoSubtitle, setPromoSubtitle] = useState("");
  const [promoBadge, setPromoBadge] = useState("INFO");
  const [promoType, setPromoType] = useState<"banner" | "flash_offer" | "combo">("banner");
  const [annTitle, setAnnTitle] = useState("");
  const [annBody, setAnnBody] = useState("");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs text-slate-600">
        <span>Listed-price billing enforced across all canteens; publish homepage highlight banners and campus announcements below.</span>
        <Badge tone="slate">Listed Pricing Only</Badge>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[#76010d]" /> Highlight Banners & Combos ({promos.length})
        </h2>
        <div className="grid grid-cols-2 gap-2">
          <Input value={promoTitle} onChange={(e) => setPromoTitle(e.target.value)} placeholder="Banner title (Fresh Lunch Bowl)" />
          <Input value={promoSubtitle} onChange={(e) => setPromoSubtitle(e.target.value)} placeholder="Subtitle / timing note" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Select value={promoType} onChange={(e) => setPromoType(e.target.value as any)}>
            <option value="banner">Campus Banner</option>
            <option value="combo">Meal Combo</option>
            <option value="flash_offer">Special Highlight</option>
          </Select>
          <Input value={promoBadge} onChange={(e) => setPromoBadge(e.target.value)} placeholder="Badge text (SPECIAL)" />
        </div>
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post("/promotions", {
                canteen_id: activeCanteenId || null,
                title: promoTitle,
                subtitle: promoSubtitle || null,
                badge_text: promoBadge || null,
                promo_type: promoType,
              });
              setPromoTitle("");
              setPromoSubtitle("");
              refetchPromos();
              pushToast("Highlight banner created", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Publish Banner
        </Button>
        <div className="space-y-1.5 pt-2 border-t border-slate-100 text-xs">
          {promos.length === 0 && <div className="text-slate-500">No active highlight banners configured.</div>}
          {promos.map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-2 rounded-lg bg-[#fdf8f0] border border-[#76010d]/15 p-2">
              <div>
                <div className="font-bold text-slate-900">
                  {p.badge_text ? `[${p.badge_text}] ` : ""}{p.title}
                </div>
                {p.subtitle && <div className="text-slate-600">{p.subtitle}</div>}
              </div>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api.delete(`/promotions/${p.id}`);
                    refetchPromos();
                    pushToast("Banner deactivated", "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
                className="font-bold text-red-600 hover:underline shrink-0"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-5 space-y-3">
        <h2 className="font-bold text-slate-900 flex items-center gap-2">
          <Megaphone className="h-4 w-4 text-amber-600" /> Campus Announcements ({announcements.length})
        </h2>
        <Input value={annTitle} onChange={(e) => setAnnTitle(e.target.value)} placeholder="Announcement title" />
        <Input value={annBody} onChange={(e) => setAnnBody(e.target.value)} placeholder="Announcement message..." />
        <Button
          size="sm"
          onClick={async () => {
            try {
              await api.post("/notifications/announcements", {
                canteen_id: activeCanteenId || null,
                title: annTitle,
                body: annBody,
                severity: "info",
              });
              setAnnTitle("");
              setAnnBody("");
              refetchAnn();
              pushToast("Announcement published", "success");
            } catch (err) {
              pushToast(getApiError(err), "error");
            }
          }}
        >
          Publish Announcement
        </Button>
        <div className="space-y-1.5 pt-2 border-t border-slate-100 text-xs">
          {announcements.map((a) => (
            <div key={a.id} className="flex items-start justify-between gap-2 rounded-lg bg-amber-50 p-2">
              <div>
                <div className="font-bold">{a.title}</div>
                <div className="text-slate-600">{a.body}</div>
              </div>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api.delete(`/notifications/announcements/${a.id}`);
                    refetchAnn();
                    pushToast("Announcement removed", "info");
                  } catch (err) {
                    pushToast(getApiError(err), "error");
                  }
                }}
                className="text-red-600 font-bold hover:underline shrink-0"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      </Card>
      </div>
    </div>
  );
};

export const SystemTab: React.FC<{
  college?: CollegeSettings;
  refetchCollege: () => void;
  health: any;
  auditLogs: any[];
}> = ({ college, refetchCollege, health, auditLogs }) => {
  const { pushToast } = useToast();
  const { data: payments = [], refetch: refetchPayments } = useQuery<any[]>({
    queryKey: ["admin-payments"],
    queryFn: async () => (await api.get("/payments?limit=20")).data,
  });
  const { data: kioskStatus, refetch: refetchKiosk } = useQuery<any>({
    queryKey: ["admin-kiosk-status"],
    queryFn: async () => (await api.get("/kiosk/status")).data,
  });
  const { data: sysEvents = [] } = useQuery<any[]>({
    queryKey: ["admin-system-events"],
    queryFn: async () => (await api.get("/admin/system-events")).data,
  });

  const [collegeName, setCollegeName] = useState(college?.college_name || "");
  const [policyText, setPolicyText] = useState(college?.cancellation_policy_text || "");
  const [timezone, setTimezone] = useState(college?.college_timezone || "Asia/Kolkata");

  useEffect(() => {
    if (college) {
      setCollegeName(college.college_name || "");
      setPolicyText(college.cancellation_policy_text || "");
      setTimezone(college.college_timezone || "Asia/Kolkata");
    }
  }, [college]);

  const toggleSetting = async (field: keyof CollegeSettings, val: boolean, label: string) => {
    try {
      await api.put("/admin/college", { [field]: val });
      refetchCollege();
      pushToast(`${label} ${val ? "enabled" : "disabled"}`, "info");
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2">
        <Card className="p-5 space-y-4">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <Shield className="h-4 w-4 text-emerald-600" /> College Settings & Hardware
          </h2>
          {health && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-slate-50 p-3">Database: <strong>{health.database}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Redis: <strong>{health.redis}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Orders: <strong>{health.total_orders}</strong></div>
              <div className="rounded-xl bg-slate-50 p-3">Payments: <strong>{health.total_payments}</strong></div>
            </div>
          )}
          {college && (
            <div className="space-y-3 border-t border-slate-100 pt-3 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <Input value={collegeName} onChange={(e) => setCollegeName(e.target.value)} placeholder="College Name" />
                <Input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="Timezone (Asia/Kolkata)" />
              </div>
              <textarea
                rows={3}
                value={policyText}
                onChange={(e) => setPolicyText(e.target.value)}
                className="w-full rounded-xl border border-slate-300 p-2.5 text-xs"
              />
              <div className="grid grid-cols-2 gap-2">
                <label className="flex items-center gap-1.5 font-semibold cursor-pointer">
                  <input
                    type="checkbox"
                    checked={Boolean(college.razorpay_enabled)}
                    onChange={() => void toggleSetting("razorpay_enabled", !college.razorpay_enabled, "Razorpay")}
                  />
                  Razorpay Enabled
                </label>
                <Badge tone="green">Razorpay Only (No Cash)</Badge>
                <Badge tone="blue">Password Auth (OTP Removed)</Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={async () => {
                    try {
                      await api.put("/admin/college", {
                        college_name: collegeName || college.college_name,
                        cancellation_policy_text: policyText || college.cancellation_policy_text,
                        college_timezone: timezone || "Asia/Kolkata",
                      });
                      refetchCollege();
                      pushToast("College settings saved", "success");
                    } catch (err) {
                      pushToast(getApiError(err), "error");
                    }
                  }}
                >
                  Save Settings
                </Button>
                <Button
                  size="sm"
                  variant={college.kiosk_enabled ? "success" : "outline"}
                  onClick={() => void toggleSetting("kiosk_enabled", !college.kiosk_enabled, "Kiosk Mode")}
                >
                  Kiosk: {college.kiosk_enabled ? "Enabled" : "Disabled"}
                </Button>
              </div>

              {kioskStatus?.devices?.length > 0 && (
                <div className="border-t border-slate-100 pt-2 space-y-1.5">
                  <div className="font-bold text-slate-700 flex items-center gap-1.5">
                    <Monitor className="h-3.5 w-3.5" /> Registered Kiosk Terminals
                  </div>
                  {kioskStatus.devices.map((dev: any) => (
                    <div key={dev.id} className="flex items-center justify-between rounded-lg border border-slate-200 px-2.5 py-1.5">
                      <span>
                        <strong>{dev.name}</strong> ({dev.device_code})
                      </span>
                      <Button
                        size="sm"
                        variant={dev.is_enabled ? "success" : "outline"}
                        onClick={async () => {
                          try {
                            await api.patch(`/kiosk/devices/${dev.id}`, { is_enabled: !dev.is_enabled });
                            refetchKiosk();
                            pushToast(`Device ${dev.device_code} ${!dev.is_enabled ? "enabled" : "disabled"}`, "info");
                          } catch (err) {
                            pushToast(getApiError(err), "error");
                          }
                        }}
                      >
                        {dev.is_enabled ? "Device On" : "Device Off"}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>

        <Card className="p-5 space-y-2 max-h-96 overflow-y-auto">
          <h2 className="font-bold text-slate-900">Recent Audit Logs & System Events</h2>
          {auditLogs.map((a) => (
            <div key={a.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
              <span className="font-mono font-semibold text-slate-800">{a.action}</span>
              <span className="text-slate-500">
                {a.entity_type}:{a.entity_id}
              </span>
            </div>
          ))}
          {sysEvents.slice(0, 10).map((ev) => (
            <div key={ev.id} className="border-b border-slate-100 py-1.5 text-xs flex justify-between gap-2">
              <span className="font-semibold text-amber-700">{ev.event_type}</span>
              <span className="text-slate-500 truncate">{ev.message}</span>
            </div>
          ))}
        </Card>
      </div>

      <Card className="p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold text-slate-900">Recent Payments & Reconciliation (No Refunds)</h2>
          <div className="flex flex-wrap gap-1.5 text-xs">
            <Badge tone="green">Razorpay Active (UPI / Cards / Netbanking)</Badge>
          </div>
        </div>
        <div className="space-y-2 text-xs">
          {payments.map((p) => (
            <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2">
              <div>
                <span className="font-bold">₹{p.amount}</span> • {p.provider} ({p.method}) • Ref:{" "}
                <span className="font-mono">{p.payment_reference || p.provider_order_id || "Pending"}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={p.status === "CONFIRMED" ? "green" : p.status === "FAILED" ? "red" : "amber"}>{p.status}</Badge>
                {p.status === "CONFIRMED" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.post("/payments/reconcile", { payment_id: p.id, settled_amount: p.amount, notes: "Matched" });
                        pushToast("Payment reconciled", "success");
                        refetchPayments();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Reconcile
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};
