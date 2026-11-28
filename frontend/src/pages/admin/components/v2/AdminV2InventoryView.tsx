import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowUpRight, Boxes, PackageX, Search } from "lucide-react";
import { api } from "../../../../api/client";
import { useDebouncedValue } from "../../../../hooks/useDebouncedValue";
import { Badge, Button, Input } from "../../../../components/ui/Primitives";
import { CB_V2, V2_CHART_AXIS_TICK, V2_TOOLTIP_STYLE, formatInr } from "./adminTheme";
import { V2PanelHeader } from "./AdminV2Widgets";

interface AdminV2InventoryViewProps {
  report: any;
  reportQueryCanteen: string;
}

export const AdminV2InventoryView: React.FC<AdminV2InventoryViewProps> = ({ report, reportQueryCanteen }) => {
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [lowOnly, setLowOnly] = useState(false);
  const [page, setPage] = useState(1);

  const detailParams = new URLSearchParams(
    reportQueryCanteen.startsWith("?") ? reportQueryCanteen.slice(1) : reportQueryCanteen
  );
  detailParams.set("page", String(page));
  detailParams.set("page_size", "12");
  if (debouncedSearch.trim()) detailParams.set("q", debouncedSearch.trim());
  if (lowOnly) detailParams.set("low_only", "true");

  const { data: invDetail, isLoading } = useQuery<any>({
    queryKey: ["bi-v2-inventory-detail", detailParams.toString()],
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/reports/details/inventory?${detailParams.toString()}`)).data,
  });

  const inv = report?.inventory || {};

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Inventory & Stock Intelligence"
        subtitle="Ingredient reserves, purchase receipts, wastage loss, and recipe auto-blocking alerts."
        rightSlot={
          <Link to="/inventory">
            <Button size="sm" variant="primary">
              <Boxes className="h-3.5 w-3.5" /> Open Full Stock, PO &amp; Recipe Workspace <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 text-xs">
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
          <div className="text-[#9BAFC2]">Tracked Ingredients</div>
          <div className="mt-1 text-2xl font-black text-[#F4F8FC]">{inv.tracked_ingredients ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-[#F06464]/30 bg-[#102438] p-4">
          <div className="text-[#F06464]">Low-Stock Alerts</div>
          <div className="mt-1 text-2xl font-black text-[#F06464]">{inv.low_stock_count ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-[#F5B942]/30 bg-[#102438] p-4">
          <div className="text-[#F5B942]">Unavailable Dishes</div>
          <div className="mt-1 text-2xl font-black text-[#F5B942]">{inv.out_of_stock_products_count ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
          <div className="text-[#9BAFC2]">Expiring ≤ 7 Days</div>
          <div className="mt-1 text-2xl font-black text-[#20C5D8]">{inv.expiring_within_7_days ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4">
          <div className="text-[#9BAFC2]">Recorded Wastage Loss</div>
          <div className="mt-1 text-2xl font-black text-[#F06464]">{formatInr(inv.total_wastage_loss ?? 0)}</div>
        </div>
      </div>

      {/* Stock Movement & Wastage Chart + Alerts */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 lg:col-span-2">
          <h3 className="text-sm font-extrabold text-[#F4F8FC] mb-3">
            Ingredient Consumption, Restock &amp; Wastage Trend
          </h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={inv.consumption_trends || []}>
                <CartesianGrid stroke={CB_V2.gridStroke} strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={V2_CHART_AXIS_TICK} />
                <YAxis tick={V2_CHART_AXIS_TICK} />
                <Tooltip contentStyle={V2_TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#9BAFC2" }} />
                <Line isAnimationActive={false} type="monotone" dataKey="consumed_qty" name="Consumed" stroke="#20C5D8" strokeWidth={2} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="restocked_qty" name="Restocked" stroke="#22C58B" strokeWidth={2} dot={false} />
                <Line isAnimationActive={false} type="monotone" dataKey="wastage_qty" name="Wasted" stroke="#F5B942" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-extrabold text-[#F4F8FC]">
            <PackageX className="h-4 w-4 text-[#F06464]" /> Immediate Attention
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(inv.low_stock_items || []).slice(0, 8).map((item: any) => (
              <Badge key={item.inventory_item_id} tone="red">
                {item.ingredient_name}: {item.current_quantity}/{item.reorder_level} {item.unit}
              </Badge>
            ))}
            {(inv.out_of_stock_products || []).slice(0, 6).map((p: any) => (
              <Badge key={p.food_item_id} tone="amber">
                {p.item_name} ({p.reason})
              </Badge>
            ))}
            {(inv.low_stock_items || []).length === 0 && (inv.out_of_stock_products || []).length === 0 && (
              <span className="text-xs text-[#22C58B]">All tracked ingredients are above reorder levels.</span>
            )}
          </div>
        </div>
      </div>

      {/* Paginated Inventory Table */}
      <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-extrabold text-[#F4F8FC]">Ingredient Ledger ({invDetail?.total ?? 0})</h3>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-[#9BAFC2] cursor-pointer">
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
            <div className="relative">
              <Search className="h-3.5 w-3.5 text-[#9BAFC2] absolute left-3 top-2.5" />
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                placeholder="Search ingredient..."
                className="pl-8 w-52 text-xs"
              />
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="py-8 text-center text-xs text-[#9BAFC2]">Loading inventory consumption...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#368BEA]/20 text-[11px] uppercase text-[#9BAFC2]">
                  <th className="py-2 pr-3">Ingredient</th>
                  <th className="py-2 pr-3">Consumed</th>
                  <th className="py-2 pr-3">Restocked</th>
                  <th className="py-2 pr-3">Wasted</th>
                  <th className="py-2 pr-3">Current Stock</th>
                  <th className="py-2 pr-3">Reorder Level</th>
                  <th className="py-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#368BEA]/15">
                {(invDetail?.items || []).map((row: any) => (
                  <tr key={row.inventory_item_id}>
                    <td className="py-2.5 pr-3 font-bold text-[#F4F8FC]">{row.ingredient_name}</td>
                    <td className="py-2.5 pr-3">{row.consumed_quantity} {row.unit}</td>
                    <td className="py-2.5 pr-3 text-[#22C58B]">+{row.restocked_quantity} {row.unit}</td>
                    <td className="py-2.5 pr-3 text-[#F5B942]">{row.wastage_quantity} {row.unit}</td>
                    <td className="py-2.5 pr-3 font-bold text-[#20C5D8]">{row.current_quantity} {row.unit}</td>
                    <td className="py-2.5 pr-3">{row.reorder_level} {row.unit}</td>
                    <td className="py-2.5 text-right">
                      <Badge tone={row.is_low_stock ? "red" : "green"}>{row.is_low_stock ? "LOW STOCK" : "Healthy"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-[#368BEA]/15 pt-3 text-xs text-[#9BAFC2]">
          <span>
            Page <strong className="text-[#F4F8FC]">{invDetail?.page ?? page}</strong> of{" "}
            <strong className="text-[#F4F8FC]">{invDetail?.total_pages ?? 1}</strong>
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= (invDetail?.total_pages ?? 1)}
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
