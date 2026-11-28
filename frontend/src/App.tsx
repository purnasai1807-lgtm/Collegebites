import React, { Suspense, lazy } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navbar } from "./components/layout/Navbar";
import { OfflineBanner } from "./components/layout/OfflineBanner";
import { MobileAppNav } from "./components/layout/MobileAppNav";
import { BrandFooter, BrandLoadingState, BrandLogo } from "./components/branding/BrandLogo";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { Button, Card, ToastProvider } from "./components/ui/Primitives";
import { useAppStore } from "./store/useAppStore";
import { HomePage } from "./pages/customer/HomePage";

// Route-level code splitting so customers on `/` do not download Admin, Recharts, or QR scanner chunks eagerly
const AuthPage = lazy(() => import("./pages/auth/AuthPage").then((m) => ({ default: m.AuthPage })));
const ScanQRPage = lazy(() => import("./pages/customer/ScanQRPage").then((m) => ({ default: m.ScanQRPage })));
const CheckoutPage = lazy(() => import("./pages/customer/CheckoutPage").then((m) => ({ default: m.CheckoutPage })));
const OrderTrackingPage = lazy(() =>
  import("./pages/customer/OrderTrackingPage").then((m) => ({ default: m.OrderTrackingPage }))
);
const MyOrdersPage = lazy(() => import("./pages/customer/MyOrdersPage").then((m) => ({ default: m.MyOrdersPage })));
const ProfilePage = lazy(() => import("./pages/customer/ProfilePage").then((m) => ({ default: m.ProfilePage })));
const SupportPage = lazy(() => import("./pages/customer/SupportPage").then((m) => ({ default: m.SupportPage })));
const KitchenDisplayPage = lazy(() =>
  import("./pages/kitchen/KitchenDisplayPage").then((m) => ({ default: m.KitchenDisplayPage }))
);
const CashierPOSPage = lazy(() =>
  import("./pages/cashier/CashierPOSPage").then((m) => ({ default: m.CashierPOSPage }))
);
const PickupScannerPage = lazy(() =>
  import("./pages/pickup/PickupScannerPage").then((m) => ({ default: m.PickupScannerPage }))
);
const TokenBoardPage = lazy(() =>
  import("./pages/board/TokenBoardPage").then((m) => ({ default: m.TokenBoardPage }))
);
const InventoryPage = lazy(() =>
  import("./pages/inventory/InventoryPage").then((m) => ({ default: m.InventoryPage }))
);
const OperationalTokenBoardPage = lazy(() =>
  import("./pages/board/OperationalTokenBoardPage").then((m) => ({ default: m.OperationalTokenBoardPage }))
);
const AdminConsolePage = lazy(() =>
  import("./pages/admin/AdminConsolePage").then((m) => ({ default: m.AdminConsolePage }))
);
const KioskPage = lazy(() => import("./pages/kiosk/KioskPage").then((m) => ({ default: m.KioskPage })));
const StaffPortalPage = lazy(() =>
  import("./pages/staff/StaffPortalPage").then((m) => ({ default: m.StaffPortalPage }))
);
const NotificationCenterPage = lazy(() =>
  import("./pages/notifications/NotificationCenterPage").then((m) => ({ default: m.NotificationCenterPage }))
);
const FoodSafetyPage = lazy(() =>
  import("./pages/food-safety/FoodSafetyPage").then((m) => ({ default: m.FoodSafetyPage }))
);
const AIAssistantPage = lazy(() =>
  import("./pages/assistant/AIAssistantPage").then((m) => ({ default: m.AIAssistantPage }))
);
const CampusIntelligencePage = lazy(() =>
  import("./pages/customer/CampusIntelligencePage").then((m) => ({ default: m.CampusIntelligencePage }))
);
const CommandCenterPage = lazy(() =>
  import("./pages/command-center/CommandCenterPage").then((m) => ({ default: m.CommandCenterPage }))
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Axios client interceptor already performs bounded GET retries on 502/503/504/network errors;
      // keeping React Query retry=false prevents 6x retry amplification under high load.
      retry: false,
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const RequireRole: React.FC<{ allowed: string[]; children: React.ReactNode }> = ({ allowed, children }) => {
  const user = useAppStore((s) => s.user);
  if (!user) {
    return (
      <div className="mx-auto max-w-md px-4 py-14">
        <Card className="p-6 text-center space-y-3">
          <BrandLogo size="md" className="mx-auto" />
          <div className="text-lg font-extrabold text-slate-900">Staff Sign-In Required</div>
          <p className="text-xs text-slate-500">Sign in with an authorized campus staff account to access this workspace.</p>
          <Link to="/login">
            <Button variant="primary" size="sm">Sign In</Button>
          </Link>
        </Card>
      </div>
    );
  }
  const roles = user.roles || [];
  const authorized = roles.includes("super_admin") || allowed.some((r) => roles.includes(r));
  if (!authorized) {
    return (
      <div className="mx-auto max-w-md px-4 py-14">
        <Card className="p-6 text-center space-y-3">
          <BrandLogo size="md" className="mx-auto" />
          <div className="text-lg font-extrabold text-slate-900">Access Restricted</div>
          <p className="text-xs text-slate-500">
            Your account does not hold the required role ({allowed.join(", ")}) for this workspace.
          </p>
          <Link to="/">
            <Button variant="outline" size="sm">Return to Menu</Button>
          </Link>
        </Card>
      </div>
    );
  }
  return <>{children}</>;
};

export function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter>
          <div className="min-h-screen flex flex-col overflow-x-hidden bg-[#fdf8f0]/40 text-slate-900 pb-20 md:pb-0">
            <Navbar />
            <OfflineBanner />
            <main id="main-content" className="flex-1">
              <Suspense fallback={<BrandLoadingState message="Loading CollegeBites workspace..." />}>
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/canteen/:canteenSlug" element={<HomePage />} />
                  <Route path="/campus-hub" element={<CampusIntelligencePage />} />
                  <Route path="/login" element={<AuthPage initialMode="login" />} />
                  <Route path="/register" element={<AuthPage initialMode="register" />} />
                  <Route path="/reset-password" element={<AuthPage initialMode="reset" />} />
                  <Route path="/scan" element={<ScanQRPage />} />
                  <Route path="/scan/:code" element={<ScanQRPage />} />
                  <Route path="/checkout" element={<CheckoutPage />} />
                  <Route path="/orders" element={<MyOrdersPage />} />
                  <Route path="/orders/:orderNumber" element={<OrderTrackingPage />} />
                  <Route path="/profile" element={<ProfilePage />} />
                  <Route path="/support" element={<SupportPage />} />
                  <Route
                    path="/kitchen"
                    element={
                      <RequireRole allowed={["kitchen_staff", "canteen_manager", "college_admin"]}>
                        <KitchenDisplayPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/cashier"
                    element={
                      <RequireRole allowed={["cashier", "canteen_manager", "college_admin"]}>
                        <CashierPOSPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/pickup"
                    element={
                      <RequireRole allowed={["pickup_staff", "cashier", "canteen_manager", "college_admin"]}>
                        <PickupScannerPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/pickup/verify"
                    element={
                      <RequireRole allowed={["pickup_staff", "cashier", "canteen_manager", "college_admin"]}>
                        <PickupScannerPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/board"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/board/:canteenId"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/display"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/display/:canteenId"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/tv"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/tv/:canteenId"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <TokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/token-board"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <OperationalTokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/token-board/:canteenId"
                    element={
                      <RequireRole allowed={["canteen_manager", "kitchen_staff", "pickup_staff", "cashier", "college_admin"]}>
                        <OperationalTokenBoardPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/inventory"
                    element={
                      <RequireRole allowed={["inventory_manager", "canteen_manager", "college_admin"]}>
                        <InventoryPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/admin"
                    element={
                      <RequireRole allowed={["canteen_manager", "college_admin"]}>
                        <AdminConsolePage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/staff"
                    element={
                      <RequireRole
                        allowed={[
                          "kitchen_staff",
                          "cashier",
                          "pickup_staff",
                          "inventory_manager",
                          "food_safety_inspector",
                          "canteen_manager",
                          "college_admin",
                        ]}
                      >
                        <StaffPortalPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/notifications"
                    element={
                      <RequireRole
                        allowed={[
                          "customer",
                          "kitchen_staff",
                          "cashier",
                          "pickup_staff",
                          "inventory_manager",
                          "food_safety_inspector",
                          "canteen_manager",
                          "college_admin",
                        ]}
                      >
                        <NotificationCenterPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/food-safety"
                    element={
                      <RequireRole
                        allowed={[
                          "food_safety_inspector",
                          "kitchen_staff",
                          "inventory_manager",
                          "canteen_manager",
                          "college_admin",
                        ]}
                      >
                        <FoodSafetyPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/assistant"
                    element={
                      <RequireRole
                        allowed={[
                          "food_safety_inspector",
                          "kitchen_staff",
                          "inventory_manager",
                          "canteen_manager",
                          "college_admin",
                        ]}
                      >
                        <AIAssistantPage />
                      </RequireRole>
                    }
                  />
                  <Route
                    path="/command-center"
                    element={
                      <RequireRole
                        allowed={[
                          "canteen_manager",
                          "college_admin",
                          "kitchen_staff",
                          "inventory_manager",
                          "pickup_staff",
                          "cashier",
                          "food_safety_inspector",
                        ]}
                      >
                        <CommandCenterPage />
                      </RequireRole>
                    }
                  />
                  <Route path="/kiosk" element={<KioskPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </main>
            <BrandFooter />
            <MobileAppNav />
          </div>
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
