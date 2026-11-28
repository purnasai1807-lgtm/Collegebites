import React, { useState } from "react";
import { ArrowUpRight, Layers, Plus, Utensils } from "lucide-react";
import { api, getApiError } from "../../../../api/client";
import type { FoodItem } from "../../../../types";
import { Badge, Button, Input, useToast } from "../../../../components/ui/Primitives";
import { formatInr } from "./adminTheme";
import { V2PanelHeader } from "./AdminV2Widgets";

interface AdminV2CategoriesViewProps {
  activeCanteenId: string;
  categories: any[];
  menuItems: FoodItem[];
  report: any;
  refetchCategories: () => void;
  onOpenMenu: () => void;
}

export const AdminV2CategoriesView: React.FC<AdminV2CategoriesViewProps> = ({
  activeCanteenId,
  categories,
  menuItems,
  report,
  refetchCategories,
  onOpenMenu,
}) => {
  const { pushToast } = useToast();
  const [catName, setCatName] = useState("");
  const [creating, setCreating] = useState(false);

  const categorySalesMap = new Map<string, { quantity: number; revenue: number }>();
  for (const c of report?.sales?.category_sales || []) {
    categorySalesMap.set(c.category, { quantity: Number(c.quantity || 0), revenue: Number(c.revenue || 0) });
  }

  const handleCreateCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = catName.trim();
    if (!trimmed || !activeCanteenId) return;
    setCreating(true);
    try {
      const slug = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `cat-${Date.now()}`;
      await api.post("/menus/categories", {
        canteen_id: activeCanteenId,
        name: trimmed,
        slug,
      });
      setCatName("");
      pushToast(`Category "${trimmed}" added`, "success");
      refetchCategories();
    } catch (err) {
      pushToast(getApiError(err, "Could not create category"), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Menu Categories"
        subtitle="Manage food categories and track category-level unit volume and verified revenue performance."
        rightSlot={
          <Button size="sm" variant="primary" onClick={onOpenMenu}>
            <Utensils className="h-3.5 w-3.5" /> Open Full Menu Builder
          </Button>
        }
      />

      <form
        onSubmit={handleCreateCategory}
        className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-4"
      >
        <div className="flex items-center gap-2 text-xs font-bold text-[#F4F8FC]">
          <Layers className="h-4 w-4 text-[#20C5D8]" /> Create New Category:
        </div>
        <Input
          value={catName}
          onChange={(e) => setCatName(e.target.value)}
          placeholder="e.g. South Indian Breakfast, Beverages, Snacks..."
          className="flex-1 min-w-[220px]"
        />
        <Button type="submit" size="sm" disabled={creating || !catName.trim()}>
          <Plus className="h-3.5 w-3.5" /> {creating ? "Adding..." : "Add Category"}
        </Button>
      </form>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {categories.map((cat: any) => {
          const itemsInCat = menuItems.filter((m) => m.category_id === cat.id);
          const availCount = itemsInCat.filter((m) => m.is_available).length;
          const salesStats = categorySalesMap.get(cat.name);

          return (
            <div
              key={cat.id}
              className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 flex flex-col justify-between gap-4"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-base font-extrabold text-[#F4F8FC]">{cat.name}</h3>
                  <Badge tone={cat.is_active !== false ? "green" : "slate"}>
                    {cat.is_active !== false ? "Active" : "Inactive"}
                  </Badge>
                </div>
                <div className="mt-1 font-mono text-[11px] text-[#9BAFC2]">/{cat.slug}</div>

                <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <div className="rounded-xl bg-[#153149] p-2.5">
                    <div className="text-[10px] text-[#9BAFC2]">Dishes</div>
                    <div className="font-bold text-[#F4F8FC]">
                      {itemsInCat.length} <span className="text-[10px] text-[#22C58B]">({availCount} avail)</span>
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#153149] p-2.5">
                    <div className="text-[10px] text-[#9BAFC2]">Qty Sold</div>
                    <div className="font-bold text-[#20C5D8]">{salesStats?.quantity ?? 0}</div>
                  </div>
                  <div className="rounded-xl bg-[#153149] p-2.5">
                    <div className="text-[10px] text-[#9BAFC2]">Revenue</div>
                    <div className="font-bold text-[#22C58B]">{formatInr(salesStats?.revenue ?? 0)}</div>
                  </div>
                </div>
              </div>

              <button
                type="button"
                onClick={onOpenMenu}
                className="inline-flex items-center gap-1 text-xs font-bold text-[#20C5D8] hover:underline self-start"
              >
                Manage items in Food &amp; Menu <ArrowUpRight className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
        {categories.length === 0 && (
          <div className="col-span-full rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-8 text-center text-xs text-[#9BAFC2]">
            No categories configured for the selected canteen yet.
          </div>
        )}
      </div>
    </div>
  );
};
