import React from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../ui/Primitives";

/** Official Main Branding Logo (LOGO 1) — used everywhere inside CollegeBites. */
export const COLLEGEBITES_LOGO_SRC = "/branding/collegebites-logo.png";

/** Official Installed App Icon (LOGO 2) — used strictly for PWA / app installation icons. */
export const COLLEGEBITES_APP_ICON_SRC = "/icons/icon-192.png";

const SIZE_CLASSES = {
  xs: "h-7 w-7 rounded-lg",
  sm: "h-9 w-9 rounded-xl",
  md: "h-11 w-11 rounded-xl",
  lg: "h-14 w-14 rounded-2xl",
  xl: "h-20 w-20 rounded-2xl",
} as const;

export const BrandLogo: React.FC<{
  size?: keyof typeof SIZE_CLASSES;
  variant?: "light" | "dark";
  className?: string;
}> = ({ size = "md", variant = "light", className }) => (
  <div
    className={cn(
      "inline-flex shrink-0 items-center justify-center overflow-hidden p-0.5 shadow-sm",
      SIZE_CLASSES[size],
      variant === "dark"
        ? "bg-[#fdf8f0] ring-1 ring-white/25"
        : "bg-[#fdf8f0] border border-[#76010d]/20",
      className
    )}
  >
    <img
      src={COLLEGEBITES_LOGO_SRC}
      alt="CollegeBites"
      className="h-full w-full aspect-square object-contain rounded-[inherit]"
      loading="eager"
      decoding="async"
    />
  </div>
);

export const BrandLoadingState: React.FC<{
  message?: string;
  className?: string;
}> = ({ message = "Loading CollegeBites...", className }) => (
  <div
    className={cn(
      "flex flex-col items-center justify-center gap-3 py-14 px-4 text-center",
      className
    )}
  >
    <div className="animate-pulse">
      <BrandLogo size="lg" />
    </div>
    <div className="text-sm font-semibold text-slate-600">{message}</div>
  </div>
);

export const BrandEmptyState: React.FC<{
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}> = ({ title, description, action, className }) => (
  <div
    className={cn(
      "flex flex-col items-center justify-center gap-3 rounded-2xl border border-[#76010d]/15 bg-[#fdf8f0]/70 p-10 text-center",
      className
    )}
  >
    <BrandLogo size="lg" />
    <div className="space-y-1 max-w-md">
      <div className="text-base font-extrabold text-slate-900">{title}</div>
      {description && <p className="text-xs text-slate-600 leading-relaxed">{description}</p>}
    </div>
    {action && <div className="pt-1">{action}</div>}
  </div>
);

const FOOTER_HIDDEN_PREFIXES = ["/board", "/display", "/tv", "/kiosk"];

export const BrandFooter: React.FC = () => {
  const { pathname } = useLocation();
  if (FOOTER_HIDDEN_PREFIXES.some((p) => pathname.startsWith(p))) {
    return null;
  }

  return (
    <footer className="no-print mt-12 border-t border-[#76010d]/15 bg-[#380106] text-[#fdf8f0]">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3.5">
          <BrandLogo size="md" variant="dark" />
          <div>
            <div className="text-base font-extrabold tracking-tight text-white">CollegeBites</div>
            <div className="text-xs text-[#fdedce]/80">
              Smart Campus Canteen Ordering, Digital Payments &amp; Live QR Tokens
            </div>
          </div>
        </div>

        <nav aria-label="Footer Navigation" className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs font-semibold text-[#fdedce]">
          <Link to="/" className="hover:text-white transition-colors">Menu</Link>
          <Link to="/orders" className="hover:text-white transition-colors">Orders &amp; Tokens</Link>
          <Link to="/support" className="hover:text-white transition-colors">Support</Link>
          <Link to="/profile" className="hover:text-white transition-colors">Profile</Link>
          <Link to="/login" className="hover:text-white transition-colors">Sign In</Link>
        </nav>

        <div className="text-[11px] text-[#fdedce]/75 md:text-right">
          <div>Strict Online Payment Portal • Verified Pickup QR</div>
          <div className="mt-0.5 text-white/60">© {new Date().getFullYear()} CollegeBites Platform</div>
        </div>
      </div>
    </footer>
  );
};
