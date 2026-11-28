import React, { Suspense, lazy, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreditCard, Download, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { api } from "../../../../api/client";
import { Badge, Button, Input, Select } from "../../../../components/ui/Primitives";
import { formatInr } from "./adminTheme";
import { MetricInfoTooltip, V2PanelHeader } from "./AdminV2Widgets";

const ReconciliationPanel = lazy(() =>
  import("../ReconciliationPanel").then((m) => ({ default: m.ReconciliationPanel }))
);

interface AdminV2PaymentsViewProps {
  report: any;
  isCollegeAdmin: boolean;
  activeCanteenId: string;
  scopeToCanteen: boolean;
  downloadBlob: (url: string, filename: string) => Promise<void>;
}

export const AdminV2PaymentsView: React.FC<AdminV2PaymentsViewProps> = ({
  report,
  isCollegeAdmin,
  activeCanteenId,
  scopeToCanteen,
  downloadBlob,
}) => {
  const [subTab, setSubTab] = useState<"transactions" | "reconciliation">("transactions");
  const [statusFilter, setStatusFilter] = useState("");
  const [searchText, setSearchText] = useState("");

  const { data: payments = [], isLoading, refetch } = useQuery<any[]>({
    queryKey: ["admin-payments-ledger", activeCanteenId, scopeToCanteen, statusFilter],
    enabled: subTab === "transactions",
    staleTime: 10_000,
    queryFn: async () => {
      const qs = new URLSearchParams();
      if ((!isCollegeAdmin || scopeToCanteen) && activeCanteenId) qs.set("canteen_id", activeCanteenId);
      if (statusFilter) qs.set("status", statusFilter);
      qs.set("limit", "200");
      return (await api.get(`/payments?${qs.toString()}`)).data;
    },
  });

  const filteredPayments = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    if (!q) return payments;
    return payments.filter((p) =>
      [p.id, p.order_id, p.provider, p.method, p.provider_order_id, p.provider_payment_id, p.payment_reference, p.status]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [payments, searchText]);

  const pay = report?.payment_stats || {};
  const fin = report?.financial_analytics || {};

  const exportCsvRows = () => {
    const headers = [
      "Payment ID",
      "Order ID",
      "Provider",
      "Method",
      "Status",
      "Amount (INR)",
      "Provider Payment ID",
      "Created At",
    ];
    const lines = [
      headers.join(","),
      ...filteredPayments.map((p) =>
        [
          p.id,
          p.order_id,
          p.provider,
          p.method || "",
          p.status,
          p.amount,
          p.provider_payment_id || "",
          p.created_at || "",
        ]
          .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
          .join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "collegebites-payments-transactions.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Payments & Transactions"
        subtitle="Real-time Razorpay & Counter POS payment attempts, collection status, and gateway reconciliation ledger."
        rightSlot={
          <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
            <button
              type="button"
              onClick={() => setSubTab("transactions")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subTab === "transactions" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Transaction Ledger
            </button>
            <button
              type="button"
              onClick={() => setSubTab("reconciliation")}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subTab === "reconciliation" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              Settlement Reconciliation
            </button>
          </div>
        }
      />

      {subTab === "reconciliation" ? (
        <Suspense
          fallback={
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
              Loading financial reconciliation module...
            </div>
          }
        >
          <ReconciliationPanel
            isCollegeAdmin={isCollegeAdmin}
            activeCanteenId={activeCanteenId}
            downloadBlob={downloadBlob}
          />
        </Suspense>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="flex items-center justify-between text-[11px] font-semibold uppercase text-[#9BAFC2]">
                <span>Payment Success Rate</span>
                <MetricInfoTooltip metricKey="payment_success_rate" />
              </div>
              <div className="mt-1.5 text-2xl font-black text-[#20C5D8]">{pay.success_rate_percent ?? 0}%</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">{pay.total_attempts ?? 0} gateway/POS attempts</div>
            </div>
            <div className="rounded-2xl border border-[#22C58B]/30 bg-[#102438] p-4">
              <div className="text-[11px] font-semibold uppercase text-[#22C58B]">Confirmed Captures</div>
              <div className="mt-1.5 text-2xl font-black text-[#22C58B]">{formatInr(pay.confirmed_amount ?? 0)}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">{pay.confirmed_count ?? 0} verified payments</div>
            </div>
            <div className="rounded-2xl border border-[#F5B942]/30 bg-[#102438] p-4">
              <div className="text-[11px] font-semibold uppercase text-[#F5B942]">Pending Attempts</div>
              <div className="mt-1.5 text-2xl font-black text-[#F5B942]">{formatInr(pay.pending_amount ?? 0)}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">{pay.pending_count ?? 0} awaiting gateway confirm</div>
            </div>
            <div className="rounded-2xl border border-[#F06464]/30 bg-[#102438] p-4">
              <div className="text-[11px] font-semibold uppercase text-[#F06464]">Failed Attempts</div>
              <div className="mt-1.5 text-2xl font-black text-[#F06464]">{formatInr(pay.failed_amount ?? 0)}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">{pay.failed_count ?? 0} unsuccessful attempts</div>
            </div>
            <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
              <div className="text-[11px] font-semibold uppercase text-[#9BAFC2]">Recorded Refunds</div>
              <div className="mt-1.5 text-2xl font-black text-[#F4F8FC]">{formatInr(fin.refunds_amount ?? 0)}</div>
              <div className="mt-1 text-[11px] text-[#9BAFC2]">No in-app refunds policy</div>
            </div>
          </div>

          <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-[#20C5D8]" />
                <h3 className="text-sm font-extrabold text-[#F4F8FC]">
                  Transaction Records ({filteredPayments.length})
                </h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-[#22C58B]/15 px-2 py-0.5 text-[10px] font-bold text-[#22C58B]">
                  <ShieldCheck className="h-3 w-3" /> Verified DB Ledger
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="h-3.5 w-3.5 text-[#9BAFC2] absolute left-3 top-2.5" />
                  <Input
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    placeholder="Search txn / payment ID..."
                    className="pl-8 w-56 text-xs"
                  />
                </div>
                <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-40 text-xs">
                  <option value="">All Statuses</option>
                  <option value="CONFIRMED">CONFIRMED</option>
                  <option value="PENDING">PENDING</option>
                  <option value="FAILED">FAILED</option>
                </Select>
                <Button size="sm" variant="outline" onClick={exportCsvRows}>
                  <Download className="h-3.5 w-3.5" /> Export CSV
                </Button>
                <Button size="sm" variant="outline" onClick={() => void refetch()}>
                  <RefreshCw className="h-3.5 w-3.5" /> Refresh
                </Button>
              </div>
            </div>

            {isLoading ? (
              <div className="py-10 text-center text-xs text-[#9BAFC2]">Loading payment records...</div>
            ) : filteredPayments.length === 0 ? (
              <div className="py-10 text-center text-xs text-[#9BAFC2]">
                No transaction records match the selected filter.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[#368BEA]/20 text-[11px] uppercase text-[#9BAFC2]">
                      <th className="py-2.5 pr-3">Timestamp</th>
                      <th className="py-2.5 pr-3">Gateway / Method</th>
                      <th className="py-2.5 pr-3">Provider Payment Ref</th>
                      <th className="py-2.5 pr-3">Status</th>
                      <th className="py-2.5 pr-3">Failure Note</th>
                      <th className="py-2.5 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#368BEA]/15">
                    {filteredPayments.slice(0, 100).map((p) => (
                      <tr key={p.id} className="hover:bg-[#153149]/60">
                        <td className="py-2.5 pr-3 text-[#9BAFC2]">
                          {p.created_at ? new Date(p.created_at).toLocaleString("en-IN") : "-"}
                        </td>
                        <td className="py-2.5 pr-3 font-semibold text-[#F4F8FC] uppercase">
                          {p.provider} {p.method ? `• ${p.method}` : ""}
                        </td>
                        <td className="py-2.5 pr-3 font-mono text-[11px] text-[#20C5D8]">
                          {p.provider_payment_id || p.payment_reference || p.provider_order_id || p.id.slice(0, 12)}
                        </td>
                        <td className="py-2.5 pr-3">
                          <Badge
                            tone={
                              p.status === "CONFIRMED" ? "green" : p.status === "FAILED" ? "red" : "amber"
                            }
                          >
                            {p.status}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-3 text-[11px] text-[#9BAFC2]">{p.failure_reason || "-"}</td>
                        <td className="py-2.5 text-right font-extrabold text-[#F4F8FC]">{formatInr(p.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};
