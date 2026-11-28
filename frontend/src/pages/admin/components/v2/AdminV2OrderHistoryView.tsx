import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Download, History, Search } from "lucide-react";
import { api } from "../../../../api/client";
import { useDebouncedValue } from "../../../../hooks/useDebouncedValue";
import { Badge, Button, Input, Select } from "../../../../components/ui/Primitives";
import { formatInr, formatPresetLabel } from "./adminTheme";
import { V2PanelHeader } from "./AdminV2Widgets";

interface AdminV2OrderHistoryViewProps {
  report: any;
  preset: string;
  reportQueryCanteen: string;
}

export const AdminV2OrderHistoryView: React.FC<AdminV2OrderHistoryViewProps> = ({
  report,
  preset,
  reportQueryCanteen,
}) => {
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [statusFilter, setStatusFilter] = useState("");
  const [methodFilter, setMethodFilter] = useState("");
  const [delayedOnly, setDelayedOnly] = useState(false);
  const [page, setPage] = useState(1);

  const params = new URLSearchParams(
    reportQueryCanteen.startsWith("?") ? reportQueryCanteen.slice(1) : reportQueryCanteen
  );
  params.set("page", String(page));
  params.set("page_size", "15");
  if (debouncedSearch.trim()) params.set("q", debouncedSearch.trim());
  if (statusFilter) params.set("status", statusFilter);
  if (methodFilter) params.set("payment_method", methodFilter);
  if (delayedOnly) params.set("delayed_only", "true");

  const { data: detailData, isLoading } = useQuery<any>({
    queryKey: ["bi-v2-order-history", params.toString()],
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/reports/details/orders?${params.toString()}`)).data,
  });

  const exportCsvPage = () => {
    const items = detailData?.items || [];
    const headers = ["Order Number", "Token", "Customer", "Counter", "Status", "Payment Status", "Method", "Prep (min)", "Amount (INR)", "Created At"];
    const lines = [
      headers.join(","),
      ...items.map((r: any) =>
        [
          r.order_number,
          r.token_code || "",
          r.customer_name,
          r.counter_name,
          r.status,
          r.payment_status,
          r.payment_method,
          r.prep_minutes ?? "-",
          r.total_amount,
          r.created_at || "",
        ]
          .map((c) => `"${String(c).replace(/"/g, '""')}"`)
          .join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `collegebites-order-history-page-${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Order History & Audit Archive"
        subtitle={`Paginated historical records for ${formatPresetLabel(preset, report?.range?.start_date, report?.range?.end_date)}`}
        rightSlot={
          <Button size="sm" variant="outline" onClick={exportCsvPage}>
            <Download className="h-3.5 w-3.5" /> Export Page CSV
          </Button>
        }
      />

      <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-[#20C5D8]" />
            <span className="text-sm font-extrabold text-[#F4F8FC]">
              Matching Orders ({detailData?.total ?? 0})
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-[#9BAFC2] cursor-pointer">
              <input
                type="checkbox"
                checked={delayedOnly}
                onChange={(e) => {
                  setDelayedOnly(e.target.checked);
                  setPage(1);
                }}
              />
              Delayed only
            </label>
            <div className="relative">
              <Search className="h-3.5 w-3.5 text-[#9BAFC2] absolute left-3 top-2.5" />
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Order no / Guest / Method..."
                className="pl-8 w-52 text-xs"
              />
            </div>
            <Select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="w-40 text-xs"
            >
              <option value="">All Statuses</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="READY">READY</option>
              <option value="PREPARING">PREPARING</option>
              <option value="ACCEPTED">ACCEPTED</option>
              <option value="PLACED">PLACED</option>
              <option value="CANCELLED">CANCELLED</option>
              <option value="PAYMENT_PENDING">PAYMENT_PENDING</option>
            </Select>
            <Select
              value={methodFilter}
              onChange={(e) => {
                setMethodFilter(e.target.value);
                setPage(1);
              }}
              className="w-36 text-xs"
            >
              <option value="">All Methods</option>
              <option value="razorpay">Razorpay</option>
              <option value="upi">UPI</option>
              <option value="card">Card</option>
              <option value="counter_pos">Counter POS</option>
            </Select>
          </div>
        </div>

        {isLoading ? (
          <div className="py-10 text-center text-xs text-[#9BAFC2]">Loading order history...</div>
        ) : (detailData?.items || []).length === 0 ? (
          <div className="py-10 text-center text-xs text-[#9BAFC2]">No orders found matching these filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#368BEA]/20 text-[11px] uppercase text-[#9BAFC2]">
                  <th className="py-2.5 pr-3">Order / Token</th>
                  <th className="py-2.5 pr-3">Customer</th>
                  <th className="py-2.5 pr-3">Counter</th>
                  <th className="py-2.5 pr-3">Status</th>
                  <th className="py-2.5 pr-3">Payment</th>
                  <th className="py-2.5 pr-3">Prep / Wait</th>
                  <th className="py-2.5 pr-3 text-right">Amount</th>
                  <th className="py-2.5 text-right">Receipt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#368BEA]/15">
                {(detailData?.items || []).map((row: any) => (
                  <tr key={row.order_id} className="hover:bg-[#153149]/50">
                    <td className="py-2.5 pr-3 font-bold text-[#F4F8FC]">
                      {row.order_number}{" "}
                      {row.token_code && <span className="ml-1 font-mono text-[11px] text-[#20C5D8]">• {row.token_code}</span>}
                    </td>
                    <td className="py-2.5 pr-3 text-[#9BAFC2]">{row.customer_name}</td>
                    <td className="py-2.5 pr-3 text-[#9BAFC2]">{row.counter_name}</td>
                    <td className="py-2.5 pr-3">
                      <Badge tone={row.status === "COMPLETED" ? "green" : row.status === "CANCELLED" ? "red" : "blue"}>
                        {row.status}
                      </Badge>
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge tone={row.payment_status === "CONFIRMED" ? "green" : "amber"}>
                        {row.payment_status} ({row.payment_method})
                      </Badge>
                    </td>
                    <td className="py-2.5 pr-3 text-[#9BAFC2]">
                      {row.prep_minutes ?? "-"}m / {row.pickup_wait_minutes ?? "-"}m
                    </td>
                    <td className="py-2.5 pr-3 text-right font-extrabold text-[#F4F8FC]">
                      {formatInr(row.total_amount)}
                    </td>
                    <td className="py-2.5 text-right">
                      <Link to={`/orders/${row.order_number}`}>
                        <Button size="sm" variant="outline">View</Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-[#368BEA]/15 pt-3 text-xs text-[#9BAFC2]">
          <span>
            Page <strong className="text-[#F4F8FC]">{detailData?.page ?? page}</strong> of{" "}
            <strong className="text-[#F4F8FC]">{detailData?.total_pages ?? 1}</strong> · Total{" "}
            <strong className="text-[#F4F8FC]">{detailData?.total ?? 0}</strong> orders
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
      </div>
    </div>
  );
};
