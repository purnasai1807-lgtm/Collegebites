import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "../types";

function clearPrivateClientCaches() {
  if (typeof localStorage === "undefined") return;
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (k && (k.startsWith("cb_offline_cache_v1:orders:") || k.startsWith("cb_offline_cache_v1:order:") || k.startsWith("cb_offline_cache_v1:receipt:"))) {
        keysToRemove.push(k);
      }
    }
    for (const k of keysToRemove) {
      localStorage.removeItem(k);
    }
  } catch {
    // ignore storage access issues in SSR/test contexts
  }
}

function makeGuestSessionId() {
  return "cb-guest-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

interface AppState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  guestSessionId: string;
  selectedCanteenId: string | null;
  selectedCounterId: string | null;
  selectedTableId: string | null;
  scannedLocationQrCode: string | null;
  guestOrderTokens: Record<string, string>;
  printerWidth: "58mm" | "80mm" | "a4";
  autoPrintPos: boolean;
  pendingCheckoutKey: string | null;
  pendingCheckoutCartSig: string | null;

  setAuth: (accessToken: string, refreshToken: string, user: User) => void;
  logout: () => void;
  setSelectedCanteen: (canteenId: string, counterId?: string | null, tableId?: string | null, qrCode?: string | null) => void;
  saveGuestOrderToken: (orderNumber: string, token: string) => void;
  setPrinterPrefs: (width: "58mm" | "80mm" | "a4", autoPrintPos: boolean) => void;
  getOrCreateCheckoutIdemKey: (cartSig: string) => string;
  clearCheckoutIdemKey: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      guestSessionId: makeGuestSessionId(),
      selectedCanteenId: null,
      selectedCounterId: null,
      selectedTableId: null,
      scannedLocationQrCode: null,
      guestOrderTokens: {},
      printerWidth: "80mm",
      autoPrintPos: true,
      pendingCheckoutKey: null,
      pendingCheckoutCartSig: null,

      setAuth: (accessToken, refreshToken, user) => {
        const prevUserId = get().user?.id;
        if (prevUserId && prevUserId !== user.id) {
          clearPrivateClientCaches();
        }
        set({
          accessToken,
          refreshToken,
          user,
          guestOrderTokens: prevUserId !== user.id ? {} : get().guestOrderTokens,
        });
      },
      logout: () => {
        clearPrivateClientCaches();
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          guestOrderTokens: {},
          pendingCheckoutKey: null,
          pendingCheckoutCartSig: null,
        });
      },
      setSelectedCanteen: (canteenId, counterId = null, tableId = null, qrCode = null) =>
        set({
          selectedCanteenId: canteenId,
          selectedCounterId: counterId,
          selectedTableId: tableId,
          scannedLocationQrCode: qrCode,
        }),
      saveGuestOrderToken: (orderNumber, token) =>
        set((state) => ({
          guestOrderTokens: { ...state.guestOrderTokens, [orderNumber]: token },
        })),
      setPrinterPrefs: (printerWidth, autoPrintPos) => set({ printerWidth, autoPrintPos }),
      getOrCreateCheckoutIdemKey: (cartSig) => {
        const cur = get();
        if (cur.pendingCheckoutKey && cur.pendingCheckoutCartSig === cartSig) {
          return cur.pendingCheckoutKey;
        }
        const nextKey = "cb-idem-" + Date.now() + "-" + Math.random().toString(36).slice(2, 9);
        set({ pendingCheckoutKey: nextKey, pendingCheckoutCartSig: cartSig });
        return nextKey;
      },
      clearCheckoutIdemKey: () => set({ pendingCheckoutKey: null, pendingCheckoutCartSig: null }),
    }),
    {
      name: "collegebites-app-state",
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        guestSessionId: state.guestSessionId,
        selectedCanteenId: state.selectedCanteenId,
        selectedCounterId: state.selectedCounterId,
        selectedTableId: state.selectedTableId,
        scannedLocationQrCode: state.scannedLocationQrCode,
        printerWidth: state.printerWidth,
        autoPrintPos: state.autoPrintPos,
        pendingCheckoutKey: state.pendingCheckoutKey,
        pendingCheckoutCartSig: state.pendingCheckoutCartSig,
      }),
    }
  )
);
