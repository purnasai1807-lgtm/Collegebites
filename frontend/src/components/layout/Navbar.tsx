import React, { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  BellRing,
  Bot,
  ChefHat,
  CreditCard,
  LayoutDashboard,
  LogIn,
  LogOut,
  Monitor,
  Package,
  QrCode,
  ShieldCheck,
  ShoppingBag,
  Smartphone,
  Tv,
  User as UserIcon,
} from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useRealtimeSync } from "../../hooks/useRealtimeSync";
import { useAppStore } from "../../store/useAppStore";
import type { Canteen, CartSummary, CollegeSettings } from "../../types";
import { enableBrowserPushNotifications, playOrderAlertChime, showBrowserNotification } from "../../utils/notifications";
import { usePwaInstall } from "../../utils/pwa";
import { BrandLogo, COLLEGEBITES_APP_ICON_SRC } from "../branding/BrandLogo";
import { Badge, Button, Modal, crowdBadgeTone, useToast } from "../ui/Primitives";

export const Navbar: React.FC = () => {
  const location = useLocation();
  const user = useAppStore((s) => s.user);
  const isAuthorizedAdminRoute =
    location.pathname.startsWith("/admin") &&
    Boolean(user?.roles?.some((r) => ["super_admin", "college_admin", "canteen_manager"].includes(r)));
  if (
    location.pathname.startsWith("/board") ||
    location.pathname.startsWith("/display") ||
    location.pathname.startsWith("/tv") ||
    location.pathname.startsWith("/kiosk") ||
    isAuthorizedAdminRoute
  ) {
    return null;
  }
  return <NavbarContent />;
};

const NavbarContent: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { pushToast } = useToast();
  const { user, accessToken, logout, selectedCanteenId, setSelectedCanteen } = useAppStore();
  const [notifOpen, setNotifOpen] = useState(false);
  const [installOpen, setInstallOpen] = useState(false);
  const [notifPerm, setNotifPerm] = useState<string>(() =>
    typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported"
  );
  const seenNotifIdsRef = useRef<Set<string>>(new Set());
  const seededNotifsRef = useRef(false);
  const pwa = usePwaInstall();

  const handleIncomingNotifications = (list: any[]) => {
    if (!seededNotifsRef.current) {
      for (const n of list) seenNotifIdsRef.current.add(n.id);
      seededNotifsRef.current = true;
      return;
    }
    const freshUnread = list.filter((n) => !n.is_read && !seenNotifIdsRef.current.has(n.id));
    for (const n of list) seenNotifIdsRef.current.add(n.id);
    if (freshUnread.length > 0) {
      const latest = freshUnread[0];
      playOrderAlertChime(latest.event_type === "order_ready" || latest.event_type === "order_delayed");
      pushToast(`${latest.title}: ${latest.message}`, "info");
      const orderNum = latest.metadata_json?.order_number;
      const targetUrl = orderNum
        ? `/orders/${orderNum}`
        : latest.event_type === "kitchen_new_order"
        ? "/kitchen"
        : "/orders";
      void showBrowserNotification(latest.title, latest.message, targetUrl);
      qc.invalidateQueries({ queryKey: ["my-orders"] });
    }
  };

  useEffect(() => {
    seenNotifIdsRef.current.clear();
    seededNotifsRef.current = false;
  }, [user?.id]);

  const { status: notifSyncStatus } = useRealtimeSync<{ notifications?: any[] }>({
    enabled: Boolean(user?.id && accessToken),
    ssePath: user?.id ? "/realtime/notifications/stream" : null,
    wsPath: user?.id ? `/ws/notifications/${user.id}` : null,
    queryKeys: [["notifications-my"], ["my-orders"]],
    onSnapshot: (snap) => {
      if (snap?.notifications) {
        qc.setQueryData(["notifications-my"], snap.notifications);
        handleIncomingNotifications(snap.notifications);
      }
    },
  });

  const { data: college } = useQuery<CollegeSettings>({
    queryKey: ["college-settings"],
    staleTime: 300_000,
    queryFn: async () => (await api.get("/canteens/college")).data,
  });

  const { data: canteens = [] } = useQuery<Canteen[]>({
    queryKey: ["canteens"],
    staleTime: 15_000,
    queryFn: async () => (await api.get("/canteens")).data,
  });

  const activeCanteen = canteens.find((c) => c.id === selectedCanteenId) || canteens[0];
  const isStaffOrAuthRoute = /^\/(admin|command-center|kitchen|inventory|pickup|food-safety|assistant|staff|token-board|cashier|login|register|reset-password)/.test(
    location.pathname
  );

  const { data: cart } = useQuery<CartSummary>({
    queryKey: ["cart", activeCanteen?.id],
    enabled: Boolean(activeCanteen?.id) && !isStaffOrAuthRoute,
    staleTime: 15_000,
    queryFn: async () => (await api.get(`/carts?canteen_id=${activeCanteen!.id}`)).data,
  });

  const { data: notifications = [] } = useQuery<any[]>({
    queryKey: ["notifications-my"],
    enabled: Boolean(user),
    staleTime: 30_000,
    queryFn: async () => {
      const list = (await api.get("/notifications/my")).data;
      handleIncomingNotifications(list);
      return list;
    },
    refetchInterval: () =>
      typeof navigator !== "undefined" && navigator.onLine === false
        ? false
        : notifSyncStatus === "live"
        ? 180_000
        : 60_000,
    refetchIntervalInBackground: false,
  });

  const unreadCount = notifications.filter((n) => !n.is_read).length;
  const cartQty = cart?.items?.reduce((s, i) => s + i.quantity, 0) || 0;
  const roles = new Set(user?.roles || []);
  const isStaff = (r: string[]) => roles.has("super_admin") || r.some((x) => roles.has(x));

  return (
    <>
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur-md no-print">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandLogo size="md" />
            <div>
              <div className="text-lg font-extrabold tracking-tight text-slate-900">CollegeBites</div>
              <div className="text-[11px] font-medium text-slate-500">
                {college?.college_name || "Campus Smart Canteen"}
              </div>
            </div>
          </Link>

          {canteens.length > 0 && (
            <div className="hidden md:flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5">
              <select
                value={activeCanteen?.id || ""}
                onChange={(e) => setSelectedCanteen(e.target.value)}
                className="bg-transparent text-xs font-bold text-slate-800 focus:outline-none"
                aria-label="Select Canteen"
              >
                {canteens.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {activeCanteen && (
                <Badge tone={crowdBadgeTone(activeCanteen.crowd_level)}>
                  {activeCanteen.crowd_level.replace("_", " ")} • ~{activeCanteen.estimated_wait_minutes}m
                </Badge>
              )}
            </div>
          )}
        </div>

        <nav aria-label="Main navigation" className="flex flex-wrap items-center gap-1.5">
          <Link to="/" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Menu
          </Link>
          <Link to="/campus-hub" className="rounded-lg bg-[#fdf8f0] border border-[#76010d]/20 px-2.5 py-1.5 text-xs font-bold text-[#76010d] hover:bg-[#fdedce]">
            Campus Live &amp; Voice
          </Link>
          <Link to="/orders" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            {user ? "My Orders & Receipts" : "My Receipts"}
          </Link>
          <Link to="/support" className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">
            Support
          </Link>
          {isStaff(["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]) && (
            <Link
              to="/token-board"
              className="inline-flex items-center gap-1 rounded-lg bg-[#fdf8f0] border border-[#76010d]/25 px-2.5 py-1.5 text-xs font-bold text-[#76010d] hover:bg-[#fdedce]"
            >
              <Tv className="h-3.5 w-3.5" /> Token Board
            </Link>
          )}

          {isStaff(["kitchen_staff", "canteen_manager", "college_admin"]) && (
            <Link
              to="/kitchen"
              className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
            >
              <ChefHat className="h-3.5 w-3.5" /> Kitchen
            </Link>
          )}
          {isStaff(["cashier", "canteen_manager", "college_admin"]) && (
            <Link
              to="/cashier"
              className="inline-flex items-center gap-1 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100"
            >
              <CreditCard className="h-3.5 w-3.5" /> Cashier POS
            </Link>
          )}
          {isStaff(["pickup_staff", "cashier", "canteen_manager", "college_admin"]) && (
            <Link
              to="/pickup"
              className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100"
            >
              <QrCode className="h-3.5 w-3.5" /> Pickup Scan
            </Link>
          )}
          {isStaff(["inventory_manager", "canteen_manager", "college_admin"]) && (
            <Link
              to="/inventory"
              className="inline-flex items-center gap-1 rounded-lg bg-purple-50 px-2.5 py-1.5 text-xs font-semibold text-purple-800 hover:bg-purple-100"
            >
              <Package className="h-3.5 w-3.5" /> Inventory
            </Link>
          )}
          {isStaff(["food_safety_inspector", "kitchen_staff", "inventory_manager", "canteen_manager", "college_admin"]) && (
            <Link
              to="/food-safety"
              className="inline-flex items-center gap-1 rounded-lg bg-teal-50 px-2.5 py-1.5 text-xs font-semibold text-teal-800 hover:bg-teal-100"
            >
              <ShieldCheck className="h-3.5 w-3.5" /> Food Safety
            </Link>
          )}
          {isStaff(["food_safety_inspector", "kitchen_staff", "inventory_manager", "canteen_manager", "college_admin"]) && (
            <Link
              to="/assistant"
              className="inline-flex items-center gap-1 rounded-lg bg-indigo-50 px-2.5 py-1.5 text-xs font-semibold text-indigo-800 hover:bg-indigo-100"
            >
              <Bot className="h-3.5 w-3.5" /> AI Ops
            </Link>
          )}
          {isStaff(["canteen_manager", "college_admin"]) && (
            <Link
              to="/command-center"
              className="inline-flex items-center gap-1 rounded-lg bg-[#76010d] px-2.5 py-1.5 text-xs font-bold text-white hover:bg-[#5d010a]"
            >
              <Bot className="h-3.5 w-3.5" /> Command Center
            </Link>
          )}
          {isStaff(["canteen_manager", "college_admin"]) && (
            <Link
              to="/admin"
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
            >
              <LayoutDashboard className="h-3.5 w-3.5" /> Admin
            </Link>
          )}
          {isStaff(["kitchen_staff", "cashier", "pickup_staff", "inventory_manager", "food_safety_inspector", "canteen_manager", "college_admin"]) && (
            <Link
              to="/staff"
              className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-200"
            >
              My Shifts
            </Link>
          )}
          {college?.kiosk_enabled && (
            <Link
              to="/kiosk"
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              <Monitor className="h-3.5 w-3.5" /> Kiosk
            </Link>
          )}
        </nav>

        <div className="flex items-center gap-2">
          {!pwa.installed && (
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                const outcome = await pwa.promptInstall();
                if (outcome === "manual") setInstallOpen(true);
              }}
              title="Install CollegeBites Mobile App"
            >
              <Smartphone className="h-4 w-4 text-[#76010d]" />
              <span className="hidden sm:inline">Get App</span>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => navigate("/checkout")} className="relative">
            <ShoppingBag className="h-4 w-4 text-[#76010d]" />
            <span>Cart</span>
            {cartQty > 0 && (
              <span className="ml-0.5 rounded-full bg-[#76010d] px-1.5 py-0.5 text-[10px] font-bold text-white">
                {cartQty}
              </span>
            )}
          </Button>

          {user ? (
            <>
              <div className="relative">
                <Button variant="ghost" size="sm" onClick={() => setNotifOpen((o) => !o)} className="relative" aria-label="Notifications">
                  <Bell className="h-4 w-4" />
                  {unreadCount > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 h-4 w-4 rounded-full bg-red-600 text-[10px] font-bold text-white flex items-center justify-center">
                      {unreadCount}
                    </span>
                  )}
                </Button>
                {notifOpen && (
                  <div className="absolute right-0 mt-2 w-80 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl z-50">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2">
                      <span className="text-xs font-extrabold text-slate-900">Notifications ({unreadCount} unread)</span>
                      <div className="flex items-center gap-2">
                        {notifPerm !== "granted" && notifPerm !== "unsupported" && (
                          <button
                            type="button"
                            onClick={async () => {
                              const res = await enableBrowserPushNotifications();
                              setNotifPerm(Notification.permission);
                              if (res.granted) {
                                pushToast("Browser order alerts enabled!", "success");
                              } else {
                                pushToast("Notification permission was not granted.", "info");
                              }
                            }}
                            className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 hover:underline"
                          >
                            <BellRing className="h-3 w-3" /> Push
                          </button>
                        )}
                        {unreadCount > 0 && (
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await api.post("/notifications/mark-all-read");
                                qc.invalidateQueries({ queryKey: ["notifications-my"] });
                              } catch (err) {
                                pushToast(getApiError(err), "error");
                              }
                            }}
                            className="text-[11px] font-bold text-slate-600 hover:text-[#76010d]"
                          >
                            Mark all
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setNotifOpen(false);
                            navigate("/notifications");
                          }}
                          className="text-[11px] font-bold text-[#76010d]"
                        >
                          Open Center
                        </button>
                      </div>
                    </div>
                    <div className="space-y-1.5 max-h-72 overflow-y-auto text-xs">
                      {notifications.length === 0 ? (
                        <div className="py-4 text-center text-slate-400 flex flex-col items-center gap-2">
                          <BrandLogo size="sm" />
                          <span>No notifications yet.</span>
                        </div>
                      ) : (
                        notifications.slice(0, 12).map((n) => {
                          const orderNum = n.metadata_json?.order_number;
                          const navTarget = orderNum
                            ? `/orders/${orderNum}`
                            : n.event_type === "kitchen_new_order"
                            ? "/kitchen"
                            : n.event_type === "inventory_alert" || n.event_type === "ingredient_unavailable"
                            ? "/inventory"
                            : null;
                          return (
                            <div
                              key={n.id}
                              onClick={async () => {
                                if (!n.is_read) {
                                  try {
                                    await api.post(`/notifications/${n.id}/read`);
                                    qc.invalidateQueries({ queryKey: ["notifications-my"] });
                                  } catch {
                                    // non-blocking
                                  }
                                }
                                if (navTarget) {
                                  setNotifOpen(false);
                                  navigate(navTarget);
                                }
                              }}
                              className={`rounded-xl border p-2 ${navTarget ? "cursor-pointer hover:border-[#76010d]/40" : ""} ${
                                n.is_read ? "border-slate-100 bg-white" : "border-[#76010d]/25 bg-[#fdf8f0]"
                              }`}
                            >
                              <div className="font-bold text-slate-900">{n.title}</div>
                              <div className="text-slate-600 mt-0.5 line-clamp-2">{n.message}</div>
                              {!n.is_read && (
                                <button
                                  type="button"
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      await api.post(`/notifications/${n.id}/read`);
                                      qc.invalidateQueries({ queryKey: ["notifications-my"] });
                                    } catch (err) {
                                      pushToast(getApiError(err), "error");
                                    }
                                  }}
                                  className="mt-1 text-[10px] font-bold text-[#76010d]"
                                >
                                  Mark read
                                </button>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={() => navigate("/profile")}>
                <UserIcon className="h-4 w-4" />
                <span className="hidden sm:inline">{user.full_name.split(" ")[0]}</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await api.post("/auth/logout");
                  } catch {
                    // ignore
                  }
                  logout();
                  qc.clear();
                  navigate("/");
                }}
              >
                <LogOut className="h-3.5 w-3.5" />
              </Button>
            </>
          ) : (
            <Button variant="primary" size="sm" onClick={() => navigate("/login")}>
              <LogIn className="h-3.5 w-3.5" /> Sign In
            </Button>
          )}
        </div>
      </div>
    </header>

    <Modal open={installOpen} onClose={() => setInstallOpen(false)} title="Install CollegeBites Mobile App" maxWidth="max-w-md">
        <div className="space-y-4 text-sm text-slate-700">
          <div className="flex items-center gap-3 rounded-2xl border border-[#76010d]/20 bg-[#fdf8f0] p-3">
            <img
              src={COLLEGEBITES_APP_ICON_SRC}
              alt="CollegeBites Installed App Icon"
              className="h-14 w-14 shrink-0 rounded-xl object-contain"
            />
            <div>
              <div className="font-extrabold text-slate-900">CollegeBites App</div>
              <div className="text-xs text-slate-600">
                Installed home-screen &amp; desktop icon for instant ordering, live tracking &amp; QR pickup tokens.
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1.5">
            <div className="font-bold text-slate-900">iPhone / iPad (Safari)</div>
            <ol className="list-decimal list-inside text-xs text-slate-600 space-y-1">
              <li>Tap the <strong>Share</strong> icon in Safari&apos;s toolbar.</li>
              <li>Scroll and tap <strong>Add to Home Screen</strong>.</li>
              <li>Tap <strong>Add</strong> — CollegeBites launches full-screen like a native app.</li>
            </ol>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1.5">
            <div className="font-bold text-slate-900">Android (Chrome / Edge)</div>
            <ol className="list-decimal list-inside text-xs text-slate-600 space-y-1">
              <li>Tap browser menu <strong>⋮</strong> (top right).</li>
              <li>Tap <strong>Install app</strong> or <strong>Add to Home screen</strong>.</li>
            </ol>
            {pwa.canPrompt && (
              <Button
                className="w-full mt-2"
                size="sm"
                onClick={async () => {
                  const res = await pwa.promptInstall();
                  if (res === "accepted") setInstallOpen(false);
                }}
              >
                Install Now
              </Button>
            )}
          </div>
          <div className="rounded-xl border border-[#76010d]/20 bg-[#fdf8f0] p-3 text-xs text-[#380106]">
            <strong>Native Android &amp; iOS App:</strong> Supports deep links (<span className="font-mono">collegebites://</span>), live QR camera scanning, and push notifications via the Expo mobile app (<span className="font-mono">mobile/</span>).
          </div>
        </div>
      </Modal>
    </>
  );
};
