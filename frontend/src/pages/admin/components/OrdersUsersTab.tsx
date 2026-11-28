import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ClipboardList, Flame, PackageCheck, Play, Search, ShieldCheck } from "lucide-react";
import { api, getApiError } from "../../../api/client";
import { useDebouncedValue } from "../../../hooks/useDebouncedValue";
import { useAppStore } from "../../../store/useAppStore";
import { Badge, Button, Card, ConfirmModal, Input, Modal, Select, useToast } from "../../../components/ui/Primitives";
import { RealtimeStatusBadge } from "../../../components/ui/RealtimeStatusBadge";

interface OrdersUsersTabProps {
  activeCanteenId: string;
  syncStatus?: React.ComponentProps<typeof RealtimeStatusBadge>["status"];
  lastSyncedAt?: Date | null;
  triggerSync?: () => void;
  sectionMode?: "all" | "orders" | "users";
}

export const OrdersUsersTab: React.FC<OrdersUsersTabProps> = ({
  activeCanteenId,
  syncStatus = "live",
  lastSyncedAt = null,
  triggerSync,
  sectionMode = "all",
}) => {
  const { pushToast } = useToast();
  const qc = useQueryClient();
  const { user } = useAppStore();
  const [statusFilter, setStatusFilter] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const debouncedOrderSearch = useDebouncedValue(orderSearch, 300);
  const [userKindFilter, setUserKindFilter] = useState("");
  const [scopeCanteenOnly, setScopeCanteenOnly] = useState(false);
  const [roleEdits, setRoleEdits] = useState<Record<string, string>>({});
  const [permModalUser, setPermModalUser] = useState<any | null>(null);
  const [grantCodes, setGrantCodes] = useState<string[]>([]);
  const [revokeCodes, setRevokeCodes] = useState<string[]>([]);
  const [cancelOrderTarget, setCancelOrderTarget] = useState<any | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);

  const isCollegeAdmin = Boolean(user?.roles?.some((r) => r === "super_admin" || r === "college_admin"));

  const { data: orders = [], refetch: refetchOrders } = useQuery<any[]>({
    queryKey: ["admin-all-orders", activeCanteenId, statusFilter, debouncedOrderSearch, scopeCanteenOnly],
    staleTime: 10_000,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (scopeCanteenOnly && activeCanteenId) params.set("canteen_id", activeCanteenId);
      if (statusFilter) params.set("status", statusFilter);
      if (debouncedOrderSearch.trim()) params.set("q", debouncedOrderSearch.trim());
      params.set("limit", "100");
      return (await api.get(`/admin/orders?${params.toString()}`)).data;
    },
    refetchInterval: syncStatus === "live" ? 30000 : 12000,
    refetchIntervalInBackground: false,
  });

  const runOrderStage = async (
    order: any,
    stage: "accept" | "start-preparing" | "mark-ready" | "handover"
  ) => {
    setActionBusyId(order.id);
    try {
      if (stage === "handover") {
        await api.post("/pickup/handover", {
          order_id: order.id,
          counter_id: order.counter_id || null,
          verification_method: "manual_token",
        });
        pushToast(`Order ${order.order_number} handed over & completed`, "success");
      } else {
        await api.post(`/kitchen/orders/${order.id}/${stage}`);
        pushToast(`Order ${order.order_number} updated`, "success");
      }
      refetchOrders();
      qc.invalidateQueries({ queryKey: ["admin-report"] });
      qc.invalidateQueries({ queryKey: ["admin-queue"] });
      triggerSync?.();
    } catch (err) {
      pushToast(getApiError(err, "Order update failed"), "error");
    } finally {
      setActionBusyId(null);
    }
  };

  const { data: allPermissions = [] } = useQuery<any[]>({
    queryKey: ["admin-all-permissions"],
    enabled: Boolean(isCollegeAdmin),
    queryFn: async () => (await api.get("/admin/permissions")).data,
  });

  const { data: users = [], refetch: refetchUsers } = useQuery<any[]>({
    queryKey: ["admin-all-users", userKindFilter],
    queryFn: async () => {
      const qs = userKindFilter ? `?user_kind=${encodeURIComponent(userKindFilter)}` : "";
      return (await api.get(`/admin/users${qs}`)).data;
    },
  });

  return (
    <div className="space-y-6">
      {(sectionMode === "all" || sectionMode === "orders") && (
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="font-bold text-slate-900 flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-[#76010d]" /> All Campus Orders ({orders.length})
            </h2>
            <RealtimeStatusBadge status={syncStatus} lastSyncedAt={lastSyncedAt} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={scopeCanteenOnly}
                onChange={(e) => setScopeCanteenOnly(e.target.checked)}
              />
              Selected Canteen Only
            </label>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
              <Input
                value={orderSearch}
                onChange={(e) => setOrderSearch(e.target.value)}
                placeholder="Order No / Token / Guest..."
                className="pl-8 w-52"
              />
            </div>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-40">
              <option value="">All Statuses</option>
              <option value="PLACED">PLACED</option>
              <option value="ACCEPTED">ACCEPTED</option>
              <option value="PREPARING">PREPARING</option>
              <option value="READY">READY</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="CANCELLED">CANCELLED</option>
              <option value="PAYMENT_PENDING">PAYMENT_PENDING</option>
            </Select>
          </div>
        </div>

        <div className="space-y-2 max-h-96 overflow-y-auto text-xs">
          {orders.map((o) => (
            <div key={o.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3">
              <div>
                <div className="flex flex-wrap items-center gap-2 font-bold text-sm">
                  <span>{o.order_number}</span>
                  {o.pickup_token_code && <Badge tone="default">Token {o.pickup_token_code}</Badge>}
                  <Badge tone={o.payment_status === "CONFIRMED" ? "green" : "amber"}>{o.payment_status}</Badge>
                  <Badge tone="slate">{o.status}</Badge>
                </div>
                <div className="text-slate-500 mt-1">
                  {o.canteen_name} • {o.guest_name || "Registered Customer"} • ₹{o.total_amount} ({o.payment_method})
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {o.status === "PLACED" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={actionBusyId === o.id}
                    onClick={() => runOrderStage(o, "accept")}
                  >
                    <Check className="h-3.5 w-3.5" /> Accept
                  </Button>
                )}
                {o.status === "ACCEPTED" && (
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={actionBusyId === o.id}
                    onClick={() => runOrderStage(o, "start-preparing")}
                  >
                    <Play className="h-3.5 w-3.5" /> Prepare
                  </Button>
                )}
                {o.status === "PREPARING" && (
                  <Button
                    size="sm"
                    variant="success"
                    disabled={actionBusyId === o.id}
                    onClick={() => runOrderStage(o, "mark-ready")}
                  >
                    <Flame className="h-3.5 w-3.5" /> Mark Ready
                  </Button>
                )}
                {o.status === "READY" && (
                  <Button
                    size="sm"
                    variant="success"
                    disabled={actionBusyId === o.id}
                    onClick={() => runOrderStage(o, "handover")}
                  >
                    <PackageCheck className="h-3.5 w-3.5" /> Complete Handover
                  </Button>
                )}
                <Link to={`/orders/${o.order_number}`}>
                  <Button size="sm" variant="outline">
                    View Receipt
                  </Button>
                </Link>
                {["PAYMENT_PENDING", "PLACED", "ACCEPTED"].includes(o.status) && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setCancelOrderTarget(o)}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
      )}

      {(sectionMode === "all" || sectionMode === "users") && (
      <Card className="p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-bold text-slate-900 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Customers, Users & Permissions ({users.length})
          </h2>
          <Select value={userKindFilter} onChange={(e) => setUserKindFilter(e.target.value)} className="w-44">
            <option value="">All Accounts</option>
            <option value="customer">Customers</option>
            <option value="staff">Staff</option>
            <option value="admin">Admins</option>
          </Select>
        </div>

        <div className="space-y-2 max-h-96 overflow-y-auto text-xs">
          {users.map((u) => {
            const currentRole = roleEdits[u.id] ?? u.roles?.[0] ?? "customer";
            return (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3">
                <div>
                  <div className="flex items-center gap-2 font-bold text-sm text-slate-900">
                    <span>{u.full_name}</span>
                    <Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? "Active" : "Suspended"}</Badge>
                    {(u.roles || []).map((r: string) => (
                      <Badge key={r} tone="slate">
                        {r}
                      </Badge>
                    ))}
                  </div>
                  <div className="text-slate-500 mt-0.5">
                    {u.email || u.phone || "No contact"} • Type: {u.user_kind}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={currentRole}
                    onChange={(e) => setRoleEdits((p) => ({ ...p, [u.id]: e.target.value }))}
                    className="w-40"
                  >
                    <option value="customer">customer</option>
                    <option value="cashier">cashier</option>
                    <option value="kitchen_staff">kitchen_staff</option>
                    <option value="pickup_staff">pickup_staff</option>
                    <option value="inventory_manager">inventory_manager</option>
                    <option value="canteen_manager">canteen_manager</option>
                    <option value="college_admin">college_admin</option>
                    <option value="super_admin">super_admin</option>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/users/${u.id}/roles`, {
                          role_names: [currentRole],
                          canteen_id: activeCanteenId || null,
                        });
                        pushToast("User role updated", "success");
                        refetchUsers();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    Save Role
                  </Button>
                  {isCollegeAdmin && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setPermModalUser(u);
                        setGrantCodes(u.permissions || []);
                        setRevokeCodes([]);
                      }}
                    >
                      Permissions ({u.permissions?.length || 0})
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant={u.is_active ? "danger" : "success"}
                    onClick={async () => {
                      try {
                        await api.patch(`/admin/users/${u.id}/status`, { is_active: !u.is_active });
                        pushToast(`User ${!u.is_active ? "activated" : "suspended"}`, "info");
                        refetchUsers();
                      } catch (err) {
                        pushToast(getApiError(err), "error");
                      }
                    }}
                  >
                    {u.is_active ? "Suspend" : "Activate"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
      )}

      <Modal
        open={Boolean(permModalUser)}
        onClose={() => setPermModalUser(null)}
        title={`Granular Permissions • ${permModalUser?.full_name || ""}`}
        maxWidth="max-w-xl"
      >
        {permModalUser && (
          <div className="space-y-3 text-xs">
            <p className="text-slate-500">
              Toggle custom permission grants or revocations for <strong>{permModalUser.full_name}</strong> ({(permModalUser.roles || []).join(", ")}).
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 max-h-72 overflow-y-auto">
              {allPermissions.map((p: any) => {
                const isGranted = grantCodes.includes(p.code);
                return (
                  <label key={p.code} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isGranted}
                      onChange={() => {
                        if (isGranted) {
                          setGrantCodes((prev) => prev.filter((c) => c !== p.code));
                          setRevokeCodes((prev) => Array.from(new Set([...prev, p.code])));
                        } else {
                          setGrantCodes((prev) => Array.from(new Set([...prev, p.code])));
                          setRevokeCodes((prev) => prev.filter((c) => c !== p.code));
                        }
                      }}
                    />
                    <span className="font-mono text-[11px] font-semibold text-slate-800">{p.code}</span>
                  </label>
                );
              })}
            </div>
            <Button
              className="w-full"
              onClick={async () => {
                try {
                  await api.put(`/admin/users/${permModalUser.id}/permissions`, {
                    grant: grantCodes,
                    revoke: revokeCodes,
                  });
                  pushToast("Custom permissions saved", "success");
                  setPermModalUser(null);
                  refetchUsers();
                } catch (err) {
                  pushToast(getApiError(err), "error");
                }
              }}
            >
              Save Permission Overrides
            </Button>
          </div>
        )}
      </Modal>

      <ConfirmModal
        open={Boolean(cancelOrderTarget)}
        title={`Cancel Order ${cancelOrderTarget?.order_number || ""}?`}
        message="This cancels the order cleanly while retaining immutable payment records (no in-app refunds are processed)."
        confirmLabel="Cancel Order"
        busy={cancelling}
        onCancel={() => setCancelOrderTarget(null)}
        onConfirm={async () => {
          if (!cancelOrderTarget) return;
          setCancelling(true);
          try {
            await api.post(`/orders/${cancelOrderTarget.id}/cancel`, {
              reason: "Cancelled by college administrator",
            });
            pushToast("Order cancelled (payment record retained)", "info");
            setCancelOrderTarget(null);
            refetchOrders();
          } catch (err) {
            pushToast(getApiError(err), "error");
          } finally {
            setCancelling(false);
          }
        }}
      />
    </div>
  );
};
