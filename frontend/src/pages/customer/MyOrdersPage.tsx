import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Download, Eye, Lock, Receipt, RotateCcw, Search } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import { fetchWithOfflineCache } from "../../utils/offlineSync";
import type { Order, ReceiptSnapshot } from "../../types";
import { ReceiptSlip } from "../../components/receipt/ReceiptSlip";
import { BrandEmptyState, BrandLoadingState } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Modal, useToast } from "../../components/ui/Primitives";

interface PrivateReceiptSummary {
  receipt_id: string;
  receipt_number: string;
  order_id: string;
  order_number: string;
  canteen_name: string;
  counter_name: string;
  order_status: string;
  payment_status: string;
  payment_method: string;
  total_paid: string;
  pickup_token?: string;
  order_date?: string;
  order_time?: string;
  reprint_count: number;
  items: Array<{ item_name: string; quantity: number; line_total: string }>;
  created_at?: string;
}

export const MyOrdersPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, setSelectedCanteen } = useAppStore();
  const isOnline = useOfflineStore((s) => s.isOnline);

  const [viewMode, setViewMode] = useState<"receipts" | "orders">("receipts");
  const [historyFilter, setHistoryFilter] = useState<"all" | "active" | "completed" | "cancelled">("all");
  const [historySearch, setHistorySearch] = useState("");
  const [selectedReceipt, setSelectedReceipt] = useState<ReceiptSnapshot | null>(null);
  const [loadingReceiptId, setLoadingReceiptId] = useState<string | null>(null);

  const { data: orders = [], isLoading: ordersLoading } = useQuery<Order[]>({
    queryKey: ["my-orders", user?.id],
    enabled: Boolean(user?.id),
    queryFn: () =>
      fetchWithOfflineCache(`orders:my:${user?.id}`, async () => (await api.get("/orders/my-orders")).data),
    refetchInterval: isOnline ? 15000 : false,
  });

  const { data: myReceipts = [], isLoading: receiptsLoading } = useQuery<PrivateReceiptSummary[]>({
    queryKey: ["my-receipts", user?.id],
    enabled: Boolean(user?.id),
    queryFn: () =>
      fetchWithOfflineCache(`receipt:my:${user?.id}`, async () => (await api.get("/tokens/receipts/my")).data),
    refetchInterval: isOnline ? 20000 : false,
  });

  const handleReorder = async (o: Order) => {
    try {
      let added = 0;
      const skipped: string[] = [];
      for (const it of o.items) {
        if (!it.food_item_id) continue;
        const addons: { addon_id: string; quantity: number }[] = [];
        let spiceLevel: string | null = null;
        let sugarLevel: string | null = null;
        const removedIngredients: string[] = [];
        for (const c of it.customizations || []) {
          if (c.customization_type === "addon" && c.addon_id) {
            addons.push({ addon_id: c.addon_id, quantity: c.quantity || 1 });
          } else if (c.customization_type === "spice") {
            spiceLevel = c.option_value;
          } else if (c.customization_type === "sugar") {
            sugarLevel = c.option_value;
          } else if (c.customization_type === "remove_ingredient") {
            removedIngredients.push(c.option_value);
          }
        }
        try {
          await api.post("/carts/items", {
            canteen_id: o.canteen_id,
            food_item_id: it.food_item_id,
            variant_id: it.variant_id || null,
            quantity: it.quantity,
            spice_level: spiceLevel,
            sugar_level: sugarLevel,
            removed_ingredients: removedIngredients,
            addons,
            special_instructions: it.special_instructions || null,
          });
          added += 1;
        } catch {
          skipped.push(it.item_name);
        }
      }
      if (added === 0) {
        pushToast("No reorderable menu items are currently available for this order", "error");
        return;
      }
      setSelectedCanteen(o.canteen_id);
      qc.invalidateQueries({ queryKey: ["cart", o.canteen_id] });
      pushToast(
        skipped.length > 0 ? `Added ${added} item(s). Unavailable: ${skipped.join(", ")}` : "Items added back to cart!",
        skipped.length > 0 ? "info" : "success"
      );
      navigate("/checkout");
    } catch (err) {
      pushToast(getApiError(err, "Some items are currently unavailable to reorder"), "error");
    }
  };

  const handleViewPrivateReceipt = async (receiptOrOrderId: string) => {
    setLoadingReceiptId(receiptOrOrderId);
    try {
      const res = await api.get<ReceiptSnapshot>(`/tokens/receipts/${encodeURIComponent(receiptOrOrderId)}`);
      setSelectedReceipt(res.data);
    } catch (err) {
      pushToast(getApiError(err, "Could not load your private receipt"), "error");
    } finally {
      setLoadingReceiptId(null);
    }
  };

  const handleDownloadPrivateReceiptPdf = async (receiptOrOrderId: string, orderNumber: string) => {
    try {
      const res = await api.get(`/tokens/receipts/${encodeURIComponent(receiptOrOrderId)}/pdf?format=a4`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `CollegeBites-${orderNumber}-a4.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast(getApiError(err, "Failed to download receipt PDF"), "error");
    }
  };

  if (!user) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-14">
        <Card className="p-8 text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#fdf8f0] border border-[#76010d]/20 text-[#76010d]">
            <Lock className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900">Sign In to Access My Orders &amp; Receipts</h1>
          <p className="text-sm text-slate-600 max-w-md mx-auto">
            Order tokens and receipts in CollegeBites are strictly private to each student account. Public token lists
            are disabled to protect student order and payment privacy.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <Link to="/login">
              <Button>Sign In to View My Receipts</Button>
            </Link>
            <Link to="/register">
              <Button variant="outline">Create Student Account</Button>
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  const q = historySearch.trim().toLowerCase();
  const filteredReceipts = myReceipts.filter((r) => {
    if (!q) return true;
    return (
      r.order_number.toLowerCase().includes(q) ||
      r.receipt_number.toLowerCase().includes(q) ||
      (r.pickup_token || "").toLowerCase().includes(q) ||
      r.items.some((i) => i.item_name.toLowerCase().includes(q))
    );
  });

  const filteredOrders = orders.filter((o) => {
    if (
      historyFilter === "active" &&
      !["PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY"].includes(o.status)
    )
      return false;
    if (historyFilter === "completed" && o.status !== "COMPLETED") return false;
    if (historyFilter === "cancelled" && !["CANCELLED", "REJECTED", "PAYMENT_FAILED"].includes(o.status)) return false;
    if (!q) return true;
    return (
      o.order_number.toLowerCase().includes(q) ||
      (o.pickup_token_code || "").toLowerCase().includes(q) ||
      o.items.some((i) => i.item_name.toLowerCase().includes(q))
    );
  });

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">My Orders &amp; My Receipts</h1>
          <p className="text-xs text-slate-500">
            Account-exclusive view for {user.full_name} — only your personal orders, receipts, and payment status are accessible.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={viewMode === "receipts" ? "primary" : "outline"}
            onClick={() => setViewMode("receipts")}
          >
            <Receipt className="h-3.5 w-3.5" /> My Receipts ({myReceipts.length})
          </Button>
          <Button
            size="sm"
            variant={viewMode === "orders" ? "primary" : "outline"}
            onClick={() => setViewMode("orders")}
          >
            My Orders ({orders.length})
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {viewMode === "orders" ? (
          <div className="flex flex-wrap gap-1.5">
            {(["all", "active", "completed", "cancelled"] as const).map((tabKey) => (
              <Button
                key={tabKey}
                size="sm"
                variant={historyFilter === tabKey ? "secondary" : "outline"}
                onClick={() => setHistoryFilter(tabKey)}
              >
                {tabKey === "all"
                  ? "All Orders"
                  : tabKey === "active"
                  ? "Active"
                  : tabKey === "completed"
                  ? "Completed"
                  : "Cancelled / Failed"}
              </Button>
            ))}
          </div>
        ) : (
          <div className="text-xs font-semibold text-slate-500">
            Showing verified private receipts belonging only to your account
          </div>
        )}
        <div className="relative w-64">
          <Input
            value={historySearch}
            onChange={(e) => setHistorySearch(e.target.value)}
            placeholder="Search order, receipt, or dish..."
          />
          <Search className="pointer-events-none absolute right-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
        </div>
      </div>

      {viewMode === "receipts" ? (
        receiptsLoading ? (
          <BrandLoadingState message="Loading your private receipts..." />
        ) : filteredReceipts.length === 0 ? (
          <BrandEmptyState
            title="No paid receipts yet"
            description="Complete an order checkout to receive your private QR pickup receipt here."
            action={
              <Link to="/">
                <Button size="sm">Browse Menus →</Button>
              </Link>
            }
          />
        ) : (
          <div className="space-y-3">
            {filteredReceipts.map((r) => (
              <Card key={r.receipt_id} className="p-4 flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-extrabold text-slate-900">{r.order_number}</span>
                    <span className="text-xs font-mono text-slate-500">{r.receipt_number}</span>
                    {r.pickup_token && <Badge tone="default">Token {r.pickup_token}</Badge>}
                    <Badge tone={r.order_status === "COMPLETED" || r.order_status === "READY" ? "green" : "blue"}>
                      Order: {r.order_status}
                    </Badge>
                    <Badge tone={r.payment_status === "CONFIRMED" ? "green" : "amber"}>
                      Payment: {r.payment_status}
                    </Badge>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {r.canteen_name} / {r.counter_name} • {r.order_date} {r.order_time} •{" "}
                    {r.items.map((i) => `${i.quantity}x ${i.item_name}`).join(", ")}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="mr-2 text-right">
                    <div className="font-extrabold text-slate-900">₹{r.total_paid}</div>
                    <div className="text-[11px] uppercase text-slate-500">{r.payment_method}</div>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={loadingReceiptId === r.receipt_id}
                    onClick={() => void handleViewPrivateReceipt(r.receipt_id)}
                  >
                    <Eye className="h-3.5 w-3.5" /> View Receipt
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void handleDownloadPrivateReceiptPdf(r.receipt_id, r.order_number)}
                  >
                    <Download className="h-3.5 w-3.5" /> Download Receipt
                  </Button>
                  <Link to={`/orders/${r.order_number}`}>
                    <Button size="sm" variant="ghost">
                      Track <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </Link>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : ordersLoading ? (
        <BrandLoadingState message="Loading your private order history..." />
      ) : filteredOrders.length === 0 ? (
        <BrandEmptyState
          title="No matching orders"
          description="Explore campus canteens to place your next meal order."
          action={
            <Link to="/">
              <Button size="sm">Browse menus →</Button>
            </Link>
          }
        />
      ) : (
        <div className="space-y-3">
          {filteredOrders.map((o) => (
            <Card key={o.id} className="p-4 flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-extrabold text-slate-900">{o.order_number}</span>
                  {o.pickup_token_code && <Badge tone="default">Token {o.pickup_token_code}</Badge>}
                  <Badge tone={o.status === "COMPLETED" || o.status === "READY" ? "green" : "blue"}>
                    Order: {o.status}
                  </Badge>
                  <Badge tone={o.payment_status === "CONFIRMED" ? "green" : "amber"}>
                    Payment: {o.payment_status}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {o.canteen_name} / {o.counter_name} • {new Date(o.created_at).toLocaleString()} •{" "}
                  {o.items.map((i) => `${i.quantity}x ${i.item_name}`).join(", ")}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="mr-2 text-right">
                  <div className="font-extrabold text-slate-900">₹{o.total_amount}</div>
                  <div className="text-[11px] uppercase text-slate-500">{o.payment_method}</div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => void handleReorder(o)}>
                  <RotateCcw className="h-3.5 w-3.5" /> Reorder
                </Button>
                {o.payment_status === "CONFIRMED" && (
                  <>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={loadingReceiptId === o.id}
                      onClick={() => void handleViewPrivateReceipt(o.id)}
                    >
                      <Eye className="h-3.5 w-3.5" /> View Receipt
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void handleDownloadPrivateReceiptPdf(o.id, o.order_number)}
                    >
                      <Download className="h-3.5 w-3.5" /> Download Receipt
                    </Button>
                  </>
                )}
                <Link to={`/orders/${o.order_number}`}>
                  <Button size="sm" variant="outline">
                    Track <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={Boolean(selectedReceipt)}
        onClose={() => setSelectedReceipt(null)}
        title={`Private Receipt • ${selectedReceipt?.order_number || ""}`}
      >
        {selectedReceipt && (
          <ReceiptSlip
            receipt={selectedReceipt}
            onPrinted={() => void handleViewPrivateReceipt(selectedReceipt.order_number)}
          />
        )}
      </Modal>
    </div>
  );
};
