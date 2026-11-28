import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  Flame,
  Heart,
  MapPin,
  Megaphone,
  Search,
  ShoppingBag,
  Sparkles,
  Star,
  Tag,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { useAppStore } from "../../store/useAppStore";
import { useOfflineStore } from "../../store/useOfflineStore";
import { fetchWithOfflineCache } from "../../utils/offlineSync";
import type { Canteen, CartSummary, FoodCategory, FoodItem } from "../../types";
import { BrandEmptyState, BrandLoadingState, BrandLogo } from "../../components/branding/BrandLogo";
import { Badge, Button, Card, Input, Modal, Select, crowdBadgeTone, useToast } from "../../components/ui/Primitives";

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { canteenSlug } = useParams<{ canteenSlug?: string }>();
  const [searchParams] = useSearchParams();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, selectedCanteenId, setSelectedCanteen } = useAppStore();
  const isOnline = useOfflineStore((s) => s.isOnline);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>("");
  const [vegFilter, setVegFilter] = useState<"all" | "veg" | "nonveg">("all");
  const [maxPrice, setMaxPrice] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("popularity");
  const [activeTag, setActiveTag] = useState<"all" | "featured" | "popular" | "special" | "recommended">("all");
  const [activeItem, setActiveItem] = useState<FoodItem | null>(null);

  // Customization modal state
  const [selVariantId, setSelVariantId] = useState<string>("");
  const [selSpice, setSelSpice] = useState<string>("");
  const [selSugar, setSelSugar] = useState<string>("");
  const [selRemoved, setSelRemoved] = useState<string[]>([]);
  const [selAddons, setSelAddons] = useState<Record<string, number>>({});
  const [qty, setQty] = useState(1);
  const [instructions, setInstructions] = useState("");
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewComment, setReviewComment] = useState("");

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    queryFn: () => fetchWithOfflineCache("canteens", async () => (await api.get("/canteens")).data),
    staleTime: 30_000,
    refetchInterval: isOnline ? 60_000 : false,
    refetchIntervalInBackground: false,
  });

  const activeCanteen = useMemo(
    () => canteens.find((c) => c.id === selectedCanteenId) || canteens[0],
    [canteens, selectedCanteenId]
  );

  const { data: categories = [] } = useQuery<FoodCategory[]>({
    queryKey: ["categories", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    queryFn: () =>
      fetchWithOfflineCache(`categories:${activeCanteen!.id}`, async () =>
        (await api.get(`/menus/canteens/${activeCanteen!.id}/categories`)).data
      ),
    staleTime: 180_000,
    refetchInterval: isOnline ? 300_000 : false,
    refetchIntervalInBackground: false,
  });

  // Honor QR deep-link query params (?canteen=<slug|id>&category=<id|slug>#menu) and /canteen/:canteenSlug
  useEffect(() => {
    const requestedCanteen = (canteenSlug || searchParams.get("canteen") || "").trim().toLowerCase();
    if (requestedCanteen && canteens.length > 0) {
      const matched = canteens.find(
        (c) => c.slug.toLowerCase() === requestedCanteen || c.id.toLowerCase() === requestedCanteen
      );
      if (matched && matched.id !== selectedCanteenId) {
        setSelectedCanteen(matched.id);
      }
    }
  }, [canteenSlug, searchParams, canteens, selectedCanteenId, setSelectedCanteen]);

  useEffect(() => {
    const requestedCategory = (searchParams.get("category") || "").trim().toLowerCase();
    if (requestedCategory && categories.length > 0) {
      const matched = categories.find(
        (cat) => cat.id.toLowerCase() === requestedCategory || cat.slug.toLowerCase() === requestedCategory
      );
      if (matched) setSelectedCategoryId(matched.id);
    }
  }, [searchParams, categories]);

  useEffect(() => {
    if (window.location.hash === "#menu") {
      document.getElementById("menu")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [activeCanteen?.id]);

  const { data: items = [], isLoading: itemsLoading } = useQuery<FoodItem[]>({
    queryKey: ["menu-items", activeCanteen?.id, debouncedSearch, selectedCategoryId, vegFilter, maxPrice, sortBy, activeTag],
    enabled: Boolean(activeCanteen?.id),
    staleTime: 60_000,
    refetchInterval: isOnline ? 120_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (debouncedSearch.trim()) params.set("q", debouncedSearch.trim());
      if (selectedCategoryId) params.set("category_id", selectedCategoryId);
      if (vegFilter === "veg") params.set("is_veg", "true");
      if (vegFilter === "nonveg") params.set("is_veg", "false");
      if (maxPrice) params.set("max_price", maxPrice);
      if (activeTag === "featured") params.set("featured", "true");
      if (activeTag === "popular") params.set("popular", "true");
      if (activeTag === "special") params.set("todays_special", "true");
      if (activeTag === "recommended") params.set("recommended", "true");
      params.set("available_only", "true");
      params.set("sort_by", sortBy);
      const key =
        !debouncedSearch.trim() && !selectedCategoryId && vegFilter === "all" && !maxPrice && activeTag === "all"
          ? `menu:${activeCanteen!.id}:all`
          : `menu:${activeCanteen!.id}:${params.toString()}`;
      return fetchWithOfflineCache(key, async () =>
        (await api.get(`/menus/canteens/${activeCanteen!.id}/items?${params.toString()}`)).data
      );
    },
  });

  const { data: recommended = [] } = useQuery<FoodItem[]>({
    queryKey: ["smart-recs", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    staleTime: 60_000,
    refetchInterval: isOnline ? 120_000 : false,
    refetchIntervalInBackground: false,
    queryFn: async () => (await api.get(`/kiosk/recommendations/${activeCanteen!.id}`)).data,
  });

  const availableRecommended = useMemo(
    () =>
      recommended.filter(
        (r) => r.is_available && !r.insufficient_ingredients && r.is_schedule_active_now !== false
      ),
    [recommended]
  );

  const { data: promotions = [] } = useQuery<any[]>({
    queryKey: ["promotions", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    staleTime: 120_000,
    queryFn: async () => (await api.get(`/promotions?canteen_id=${activeCanteen!.id}`)).data,
  });

  const { data: announcements = [] } = useQuery<any[]>({
    queryKey: ["announcements"],
    staleTime: 120_000,
    queryFn: async () => (await api.get(`/notifications/announcements`)).data,
  });

  const { data: cart } = useQuery<CartSummary>({
    queryKey: ["cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id),
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/carts?canteen_id=${activeCanteen!.id}`)).data,
  });

  const { data: profile } = useQuery<any>({
    queryKey: ["customer-profile"],
    enabled: Boolean(user),
    staleTime: 60_000,
    queryFn: async () => (await api.get("/customers/profile")).data,
  });

  const { data: itemReviews = [] } = useQuery<any[]>({
    queryKey: ["item-reviews", activeItem?.id],
    enabled: Boolean(activeItem?.id),
    queryFn: async () => (await api.get(`/support/items/${activeItem!.id}/reviews`)).data,
  });

  const openItemModal = (item: FoodItem) => {
    setActiveItem(item);
    const defVar = item.variants.find((v) => v.is_default && v.is_available) || item.variants.find((v) => v.is_available) || item.variants[0];
    setSelVariantId(defVar?.id || "");
    setSelSpice(item.spice_levels[0] || "");
    setSelSugar(item.sugar_levels[0] || "");
    setSelRemoved([]);
    setSelAddons({});
    setQty(1);
    setInstructions("");
  };

  const addToCartMut = useMutation({
    mutationFn: async () => {
      if (!activeItem || !activeCanteen) return;
      const addons = Object.entries(selAddons)
        .filter(([, q]) => q > 0)
        .map(([addon_id, quantity]) => ({ addon_id, quantity }));
      return (
        await api.post("/carts/items", {
          canteen_id: activeCanteen.id,
          food_item_id: activeItem.id,
          variant_id: selVariantId || null,
          quantity: qty,
          spice_level: selSpice || null,
          sugar_level: selSugar || null,
          removed_ingredients: selRemoved,
          addons,
          special_instructions: instructions || null,
        })
      ).data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cart", activeCanteen?.id] });
      pushToast(`Added ${activeItem?.name} to cart!`, "success");
      setActiveItem(null);
    },
    onError: (err) => pushToast(getApiError(err, "Could not add item"), "error"),
  });

  const toggleFav = async (foodId: string) => {
    if (!user) {
      pushToast("Sign in to save favourite dishes", "info");
      return;
    }
    const isFav = profile?.favourite_item_ids?.includes(foodId);
    try {
      if (isFav) await api.delete(`/customers/favourites/${foodId}`);
      else await api.post(`/customers/favourites/${foodId}`);
      qc.invalidateQueries({ queryKey: ["customer-profile"] });
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const submitReview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeItem) return;
    try {
      await api.post("/support/reviews", { food_item_id: activeItem.id, rating: reviewRating, comment: reviewComment });
      setReviewComment("");
      qc.invalidateQueries({ queryKey: ["item-reviews", activeItem.id] });
      qc.invalidateQueries({ queryKey: ["menu-items"] });
      pushToast("Review submitted!", "success");
    } catch (err) {
      pushToast(getApiError(err, "Login required to post review"), "error");
    }
  };

  const computeModalPrice = () => {
    if (!activeItem) return 0;
    const v = activeItem.variants.find((x) => x.id === selVariantId);
    const base = v?.absolute_price ? Number(v.absolute_price) : Number(activeItem.base_price) + Number(v?.price_delta || 0);
    const addonsTotal = Object.entries(selAddons).reduce((acc, [id, count]) => {
      const ad = activeItem.addons.find((a) => a.id === id);
      return acc + (ad ? Number(ad.price) * count : 0);
    }, 0);
    return (base + addonsTotal) * qty;
  };

  const cartTotal = Number(cart?.total_amount || 0);
  const cartCount = cart?.items?.reduce((s, i) => s + i.quantity, 0) || 0;

  const { data: myOrders = [] } = useQuery<any[]>({
    queryKey: ["my-orders", user?.id],
    enabled: Boolean(user?.id),
    staleTime: 20_000,
    queryFn: async () => (await api.get("/orders/my-orders?limit=15")).data,
    refetchInterval: (query) => {
      if (!isOnline) return false;
      const list = (query.state.data as any[]) || [];
      const hasActive = list.some((o) => ["PLACED", "ACCEPTED", "PREPARING", "READY"].includes(o.status));
      return hasActive ? 30_000 : false;
    },
    refetchIntervalInBackground: false,
  });
  const activeOrder = myOrders.find((o) =>
    ["PLACED", "ACCEPTED", "PREPARING", "READY"].includes(o.status)
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 pb-28 space-y-6">
      {activeOrder && (
        <div
          onClick={() => navigate(`/orders/${activeOrder.order_number}`)}
          className="cursor-pointer flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-500/40 bg-emerald-950 px-4 py-3 text-white shadow-sm hover:bg-emerald-900 transition"
        >
          <div className="flex items-center gap-3">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-ping" />
            <div className="text-xs sm:text-sm font-bold">
              Live Order {activeOrder.order_number} • Token{" "}
              <span className="text-[#fdedce] font-mono text-base">{activeOrder.pickup_token_code}</span> is{" "}
              <span className="underline">{activeOrder.status}</span>
              {activeOrder.queue_position && activeOrder.queue_position > 0
                ? ` • Queue #${activeOrder.queue_position} (~${activeOrder.dynamic_wait_minutes ?? activeOrder.estimated_prep_minutes}m wait)`
                : ""}
            </div>
          </div>
          <span className="text-xs font-extrabold text-emerald-300">Track Live →</span>
        </div>
      )}
      {/* Announcements Banner */}
      {announcements.length > 0 && (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <Megaphone className="h-5 w-5 shrink-0 text-amber-600" />
          <div className="flex-1">
            <span className="font-bold">{announcements[0].title}: </span>
            <span>{announcements[0].body}</span>
          </div>
        </div>
      )}

      {/* Hero + Canteen Selector */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-3xl bg-gradient-to-br from-[#2b0308] via-[#4a040c] to-[#76010d] p-6 md:p-8 text-white shadow-lg">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <BrandLogo size="md" variant="dark" />
            <div className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold text-[#fdedce]">
              <Flame className="h-3.5 w-3.5 text-[#fdedce]" /> Skip the Canteen Line • Instant QR Token
            </div>
          </div>
          <h1 className="text-2xl md:text-4xl font-extrabold tracking-tight">
            Fresh Campus Meals, Zero Counter Chaos.
          </h1>
          <p className="mt-2 max-w-xl text-sm text-[#fdedce]/85">
            Select your campus canteen, customize dishes, pay securely via UPI/Card, and receive your live pickup token & printable receipt instantly.
          </p>

          {promotions.length > 0 && (
            <div className="mt-5 flex flex-wrap gap-2">
              {promotions.slice(0, 2).map((p) => (
                <div
                  key={p.id}
                  className="inline-flex items-center gap-2 rounded-xl bg-white/10 border border-white/15 px-3 py-2 text-xs"
                >
                  <Tag className="h-3.5 w-3.5 text-[#fdedce]" />
                  <span className="font-bold text-[#fdedce]">{p.badge_text || "INFO"}</span>
                  <span>{p.title}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Live Canteen Status Card */}
        <Card className="p-5 flex flex-col justify-between bg-white">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Active Ordering Location</div>
            <div className="space-y-2">
              {canteens.map((c) => {
                const isSelected = activeCanteen?.id === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedCanteen(c.id)}
                    className={`w-full rounded-xl border p-3 text-left transition ${
                      isSelected ? "border-[#76010d] bg-[#fdf8f0]" : "border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900 text-sm">{c.name}</span>
                      <Badge tone={crowdBadgeTone(c.crowd_level)}>{c.crowd_level.replace("_", " ")}</Badge>
                    </div>
                    <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="h-3 w-3" /> {c.location}
                      </span>
                      <span className="inline-flex items-center gap-1 font-semibold text-slate-700">
                        <Clock className="h-3 w-3" /> ~{c.estimated_wait_minutes} min • {c.active_order_count} in queue
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </Card>
      </div>

      {/* Smart Recommendations Strip */}
      {availableRecommended.length > 0 && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-[#76010d]" />
            <h2 className="text-lg font-extrabold text-slate-900">Recommended Right Now</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {availableRecommended.slice(0, 3).map((item) => (
              <Card
                key={item.id}
                onClick={() => openItemModal(item)}
                className="flex cursor-pointer items-center gap-3 p-3 transition hover:border-[#76010d]/60 hover:shadow-md"
              >
                <img
                  src={item.images[0]?.image_url || "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=300"}
                  alt={item.name}
                  loading="lazy"
                  decoding="async"
                  className="h-16 w-16 rounded-xl object-cover shrink-0"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`h-2.5 w-2.5 rounded-full ${item.is_veg ? "bg-emerald-600" : "bg-red-600"}`} />
                    <span className="truncate font-bold text-sm text-slate-900">{item.name}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    ₹{item.base_price} • {item.prep_time_minutes}m • ★ {item.average_rating}
                  </div>
                </div>
                <Button size="sm" variant="primary" disabled={!activeCanteen?.is_open_now}>
                  {activeCanteen?.is_open_now ? "Add" : "Closed"}
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Search, Filter & Category Bar */}
      <Card id="menu" className="p-4 space-y-3">
        <div className="grid gap-3 md:grid-cols-5">
          <div className="relative md:col-span-2">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search dishes, ingredients..."
              className="pl-9"
            />
          </div>
          <Select value={vegFilter} onChange={(e) => setVegFilter(e.target.value as any)}>
            <option value="all">All (Veg & Non-Veg)</option>
            <option value="veg">Pure Veg Only</option>
            <option value="nonveg">Non-Veg Only</option>
          </Select>
          <Select value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)}>
            <option value="">Any Price</option>
            <option value="50">Under ₹50</option>
            <option value="80">Under ₹80</option>
            <option value="120">Under ₹120</option>
          </Select>
          <Select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="popularity">Sort: Popular</option>
            <option value="price_asc">Price: Low to High</option>
            <option value="price_desc">Price: High to Low</option>
            <option value="rating">Top Rated</option>
          </Select>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => setSelectedCategoryId("")}
            className={`rounded-full px-3.5 py-1.5 text-xs font-bold ${
              selectedCategoryId === "" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            All Categories
          </button>
          {categories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setSelectedCategoryId(cat.id)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-bold ${
                selectedCategoryId === cat.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
              }`}
            >
              {cat.name}
            </button>
          ))}
          <span className="mx-1 text-slate-300">|</span>
          {(["all", "featured", "popular", "special", "recommended"] as const).map((tag) => (
            <button
              key={tag}
              type="button"
              onClick={() => setActiveTag(tag)}
              className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${
                activeTag === tag ? "bg-[#76010d] text-white" : "bg-[#fdf8f0] text-[#76010d] border border-[#76010d]/20"
              }`}
            >
              {tag === "special" ? "Today's Special" : tag}
            </button>
          ))}
        </div>
      </Card>

      {/* Food Grid */}
      {itemsLoading ? (
        <BrandLoadingState message="Loading canteen menu..." />
      ) : items.length === 0 ? (
        <BrandEmptyState
          title={`No dishes matched your filters in ${activeCanteen?.name || "this canteen"}`}
          description="Try clearing search keywords or switching category filters."
        />
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => {
            const outOfSchedule = item.is_schedule_active_now === false;
            const unavailable = !item.is_available || item.insufficient_ingredients || outOfSchedule || !activeCanteen?.is_open_now;
            const isFav = profile?.favourite_item_ids?.includes(item.id);
            return (
              <div key={item.id} className="transition-opacity duration-200">
                <Card className="overflow-hidden flex flex-col h-full">
                  <div className="relative h-44 bg-slate-100">
                    <img
                      src={item.images[0]?.image_url || "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600"}
                      alt={item.name}
                      loading="lazy"
                      decoding="async"
                      className="h-full w-full object-cover"
                    />
                    <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
                      <Badge tone={item.is_veg ? "green" : "red"}>{item.is_veg ? "VEG" : "NON-VEG"}</Badge>
                      {item.is_todays_special && <Badge tone="amber">Special</Badge>}
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleFav(item.id)}
                      className="absolute right-3 top-3 rounded-full bg-white/90 p-2 text-slate-700 shadow hover:text-red-600"
                      aria-label="Toggle favourite"
                    >
                      <Heart className={`h-4 w-4 ${isFav ? "fill-red-500 text-red-500" : ""}`} />
                    </button>
                  </div>

                  <div className="flex flex-1 flex-col justify-between p-4">
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="font-bold text-slate-900">{item.name}</h3>
                        <span className="shrink-0 font-extrabold text-[#76010d]">₹{item.base_price}</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-500">{item.description}</p>
                      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                        <span className="inline-flex items-center gap-1 font-semibold text-amber-600">
                          <Star className="h-3.5 w-3.5 fill-amber-400" /> {item.average_rating} ({item.rating_count})
                        </span>
                        <span>• {item.prep_time_minutes} min</span>
                        {item.portion_size && <span>• {item.portion_size}</span>}
                        {item.calories && <span>• {item.calories} kcal</span>}
                        {item.nutrition_verified && (
                          <span className="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">
                            Verified Nutrition
                          </span>
                        )}
                      </div>
                      {item.allergens.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {item.allergens.map((a) => (
                            <span key={a.id} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                              Contains {a.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-500">
                        {item.variants.length > 1 ? `${item.variants.length} sizes` : "Customizable"}
                      </span>
                      <Button
                        size="sm"
                        variant={unavailable ? "outline" : "primary"}
                        disabled={unavailable}
                        onClick={() => openItemModal(item)}
                      >
                        {item.insufficient_ingredients
                          ? "Low Ingredients"
                          : !item.is_available
                          ? "Sold Out"
                          : outOfSchedule
                          ? "Outside Schedule"
                          : !activeCanteen?.is_open_now
                          ? "Canteen Closed"
                          : "Customize & Add"}
                      </Button>
                    </div>
                  </div>
                </Card>
              </div>
            );
          })}
        </div>
      )}

      {/* Floating Cart Bar */}
      {cartCount > 0 && (
        <div className="fixed bottom-20 md:bottom-4 left-1/2 z-30 -translate-x-1/2 w-[94%] max-w-xl no-print">
          <div className="flex items-center justify-between rounded-2xl bg-slate-900 px-5 py-3.5 text-white shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#76010d] font-bold">
                <ShoppingBag className="h-5 w-5" />
              </div>
              <div>
                <div className="text-sm font-bold">
                  {cartCount} {cartCount === 1 ? "item" : "items"} • ₹{cartTotal.toFixed(2)}
                </div>
                <div className="text-xs text-slate-300">
                  {activeCanteen?.name} • Est {cart?.estimated_prep_minutes} min
                </div>
              </div>
            </div>
            <Button variant="primary" size="sm" onClick={() => navigate("/checkout")}>
              Proceed to Checkout →
            </Button>
          </div>
        </div>
      )}

      {/* Food Detail & Customization Modal */}
      <Modal
        open={Boolean(activeItem)}
        onClose={() => setActiveItem(null)}
        title={activeItem?.name || "Customize Item"}
        maxWidth="max-w-xl"
      >
        {activeItem && (
          <div className="space-y-5">
            <div className="flex gap-4">
              <img
                src={activeItem.images[0]?.image_url || "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=400"}
                alt={activeItem.name}
                className="h-24 w-24 rounded-xl object-cover"
              />
              <div className="space-y-1">
                <p className="text-xs text-slate-600">{activeItem.description}</p>
                {activeItem.ingredients_text && (
                  <p className="text-[11px] text-slate-500">
                    <strong>Ingredients:</strong> {activeItem.ingredients_text}
                  </p>
                )}
                {activeItem.nutrition_verified ? (
                  <div className="space-y-1 pt-0.5">
                    <Badge tone="green">Verified Nutrition &amp; Allergen Profile</Badge>
                    <p className="text-[11px] text-slate-600">
                      {activeItem.calories != null ? `${activeItem.calories} kcal` : ""}
                      {activeItem.nutrition_info && Object.keys(activeItem.nutrition_info).length > 0
                        ? ` • ${JSON.stringify(activeItem.nutrition_info).replace(/[{}"]/g, "").replace(/,/g, " • ")}`
                        : ""}
                    </p>
                  </div>
                ) : (
                  <p className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    {activeItem.nutrition_disclaimer ||
                      "Nutrition and allergen information is unverified or unavailable; please consult canteen staff for severe allergies."}
                  </p>
                )}
                {activeItem.allergens && activeItem.allergens.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-0.5">
                    {activeItem.allergens.map((alg) => (
                      <Badge key={alg.id} tone="amber">Allergen: {alg.name}</Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Variants */}
            {activeItem.variants.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-bold uppercase text-slate-600">Select Portion / Size</label>
                <div className="grid grid-cols-2 gap-2">
                  {activeItem.variants.map((v) => {
                    const price = v.absolute_price ? Number(v.absolute_price) : Number(activeItem.base_price) + Number(v.price_delta);
                    return (
                      <button
                        key={v.id}
                        type="button"
                        disabled={!v.is_available}
                        onClick={() => setSelVariantId(v.id)}
                        className={`rounded-xl border px-3 py-2 text-left text-xs font-semibold ${
                          !v.is_available
                            ? "border-slate-100 bg-slate-50 text-slate-400 line-through cursor-not-allowed"
                            : selVariantId === v.id
                            ? "border-[#76010d] bg-[#fdf8f0] text-[#380106]"
                            : "border-slate-200"
                        }`}
                      >
                        <div className="flex justify-between">
                          <span>{v.name}</span>
                          <span>₹{price.toFixed(2)}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Spice & Sugar */}
            {activeItem.spice_levels.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-bold uppercase text-slate-600">Spice Level</label>
                <div className="flex flex-wrap gap-2">
                  {activeItem.spice_levels.map((sp) => (
                    <button
                      key={sp}
                      type="button"
                      onClick={() => setSelSpice(sp)}
                      className={`rounded-full px-3 py-1 text-xs font-bold ${
                        selSpice === sp ? "bg-[#76010d] text-white" : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {sp}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {activeItem.sugar_levels.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-bold uppercase text-slate-600">Sugar Level</label>
                <div className="flex flex-wrap gap-2">
                  {activeItem.sugar_levels.map((sg) => (
                    <button
                      key={sg}
                      type="button"
                      onClick={() => setSelSugar(sg)}
                      className={`rounded-full px-3 py-1 text-xs font-bold ${
                        selSugar === sg ? "bg-[#76010d] text-white" : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {sg}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Add-ons */}
            {activeItem.addons.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-bold uppercase text-slate-600">Add-ons & Extra Toppings</label>
                <div className="space-y-2">
                  {activeItem.addons.filter((ad) => ad.is_available).map((ad) => {
                    const c = selAddons[ad.id] || 0;
                    return (
                      <div key={ad.id} className="flex items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-xs">
                        <div>
                          <span className="font-bold text-slate-800">{ad.name}</span>
                          <span className="ml-2 text-slate-500">+₹{ad.price}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setSelAddons((p) => ({ ...p, [ad.id]: Math.max(0, (p[ad.id] || 0) - 1) }))}
                            className="h-6 w-6 rounded-md border text-center font-bold"
                          >
                            -
                          </button>
                          <span className="w-4 text-center font-bold">{c}</span>
                          <button
                            type="button"
                            onClick={() =>
                              setSelAddons((p) => ({ ...p, [ad.id]: Math.min(ad.max_quantity, (p[ad.id] || 0) + 1) }))
                            }
                            className="h-6 w-6 rounded-md border text-center font-bold"
                          >
                            +
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Removable ingredients */}
            {activeItem.removable_ingredients.length > 0 && (
              <div>
                <label className="mb-2 block text-xs font-bold uppercase text-slate-600">Remove Ingredients (Optional)</label>
                <div className="flex flex-wrap gap-2">
                  {activeItem.removable_ingredients.map((ing) => {
                    const active = selRemoved.includes(ing);
                    return (
                      <button
                        key={ing}
                        type="button"
                        onClick={() =>
                          setSelRemoved((prev) => (active ? prev.filter((x) => x !== ing) : [...prev, ing]))
                        }
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          active ? "bg-red-100 text-red-700 border border-red-300" : "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {active ? `No ${ing}` : ing}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="mb-1 block text-xs font-bold text-slate-600">Special Kitchen Instructions</label>
                <Input
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  placeholder="e.g., pack gravy separately"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-bold text-slate-600">Quantity</label>
                <div className="flex items-center justify-between rounded-xl border border-slate-300 px-3 py-1.5">
                  <button type="button" onClick={() => setQty(Math.max(1, qty - 1))} className="font-bold text-lg">
                    -
                  </button>
                  <span className="font-bold">{qty}</span>
                  <button type="button" onClick={() => setQty(qty + 1)} className="font-bold text-lg">
                    +
                  </button>
                </div>
              </div>
            </div>

            <Button
              variant="primary"
              className="w-full"
              size="lg"
              disabled={
                addToCartMut.isPending ||
                !activeCanteen?.is_open_now ||
                !activeItem.is_available ||
                activeItem.insufficient_ingredients ||
                activeItem.is_schedule_active_now === false
              }
              onClick={() => addToCartMut.mutate()}
            >
              {!activeCanteen?.is_open_now
                ? "Canteen Currently Closed"
                : !activeItem.is_available || activeItem.insufficient_ingredients
                ? "Item Currently Unavailable"
                : activeItem.is_schedule_active_now === false
                ? "Outside Serving Hours"
                : `Add to Cart • ₹${computeModalPrice().toFixed(2)}`}
            </Button>

            {/* Reviews Section */}
            <div className="border-t border-slate-200 pt-4 space-y-3">
              <div className="text-xs font-bold uppercase text-slate-600">Student Reviews ({itemReviews.length})</div>
              {itemReviews.slice(0, 3).map((r) => (
                <div key={r.id} className="rounded-xl bg-slate-50 p-2.5 text-xs">
                  <div className="font-bold text-amber-600">{"★".repeat(r.rating)}</div>
                  {r.comment && <div className="text-slate-700 mt-0.5">{r.comment}</div>}
                </div>
              ))}
              {user && (
                <form onSubmit={submitReview} className="flex gap-2">
                  <Select value={reviewRating} onChange={(e) => setReviewRating(Number(e.target.value))} className="w-24">
                    {[5, 4, 3, 2, 1].map((n) => (
                      <option key={n} value={n}>
                        {n} ★
                      </option>
                    ))}
                  </Select>
                  <Input
                    value={reviewComment}
                    onChange={(e) => setReviewComment(e.target.value)}
                    placeholder="Rate this dish..."
                  />
                  <Button type="submit" size="sm" variant="outline">
                    Post
                  </Button>
                </form>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
