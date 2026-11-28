import React, { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Download, Printer, RefreshCw, Usb, Wifi } from "lucide-react";
import { api, getApiError } from "../../api/client";
import { useAppStore } from "../../store/useAppStore";
import type { ReceiptSnapshot } from "../../types";
import { BrandLogo } from "../branding/BrandLogo";
import { Badge, Button, useToast } from "../ui/Primitives";

interface ReceiptSlipProps {
  receipt: ReceiptSnapshot;
  guestToken?: string | null;
  allowStaffReprint?: boolean;
  autoPrintOnMount?: boolean;
  onPrinted?: () => void;
}

export const ReceiptSlip: React.FC<ReceiptSlipProps> = ({
  receipt,
  guestToken,
  allowStaffReprint = false,
  autoPrintOnMount = false,
  onPrinted,
}) => {
  const { pushToast } = useToast();
  const { printerWidth, setPrinterPrefs, autoPrintPos } = useAppStore();
  const [paperSize, setPaperSize] = useState<"58mm" | "80mm" | "a4">(printerWidth);
  const [printerStatus, setPrinterStatus] = useState<string>("Browser Print Ready");
  const [lastFailedJobId, setLastFailedJobId] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);

  const autoTriggeredRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (autoPrintOnMount && receipt.order_number && autoTriggeredRef.current !== receipt.order_number) {
      autoTriggeredRef.current = receipt.order_number;
      const t = setTimeout(() => {
        window.print();
      }, 220);
      return () => clearTimeout(t);
    }
  }, [autoPrintOnMount, receipt.order_number]);

  const guestHeaders = guestToken ? { "X-Guest-Token": guestToken } : undefined;

  const handleBrowserPrint = async () => {
    setPrinting(true);
    try {
      await api.post(
        `/printing/receipts/${receipt.order_number}/print`,
        {
          printer_target: paperSize === "a4" ? "browser" : paperSize,
          paper_width: paperSize,
          is_reprint: receipt.reprint_count > 0,
        },
        { headers: guestHeaders }
      );
      setPrinterStatus("Print job logged • Opening system print dialog");
      onPrinted?.();
      setTimeout(() => window.print(), 150);
    } catch (err) {
      pushToast(getApiError(err, "Print failed"), "error");
    } finally {
      setPrinting(false);
    }
  };

  const handleDownloadPdf = async (format: "58mm" | "80mm" | "a4") => {
    try {
      const res = await api.get(
        `/tokens/receipts/${receipt.order_number}/pdf?format=${format}&reprint=${receipt.is_reprint}`,
        { responseType: "blob", headers: guestHeaders }
      );
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `CollegeBites-${receipt.order_number}-${format}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast(getApiError(err, "Failed to download PDF"), "error");
    }
  };

  const handleUsbEscPos = async () => {
    const nav = navigator as any;
    if (!nav.usb && !nav.serial) {
      pushToast("WebUSB/WebSerial not supported in this browser. Use PDF or Browser Print.", "info");
      return;
    }
    setPrinting(true);
    try {
      const escRes = await api.get(
        `/printing/receipts/${receipt.order_number}/escpos?width=${paperSize === "58mm" ? "58mm" : "80mm"}`,
        { headers: guestHeaders }
      );
      const raw = Uint8Array.from(atob(escRes.data.escpos_base64), (c) => c.charCodeAt(0));
      if (nav.serial) {
        const port = await nav.serial.requestPort();
        await port.open({ baudRate: 9600 });
        const writer = port.writable.getWriter();
        await writer.write(raw);
        writer.releaseLock();
        await port.close();
      } else if (nav.usb) {
        const device = await nav.usb.requestDevice({ filters: [] });
        await device.open();
        if (device.configuration === null) await device.selectConfiguration(1);
        const iface = device.configuration.interfaces[0];
        await device.claimInterface(iface.interfaceNumber);
        const ep = iface.alternate.endpoints.find((e: any) => e.direction === "out");
        if (ep) await device.transferOut(ep.endpointNumber, raw);
        await device.close();
      }
      await api.post(
        `/printing/receipts/${receipt.order_number}/print`,
        {
          printer_target: "usb",
          paper_width: paperSize === "58mm" ? "58mm" : "80mm",
          is_reprint: receipt.reprint_count > 0,
        },
        { headers: guestHeaders }
      );
      setPrinterStatus("Sent ESC/POS payload to thermal printer");
      pushToast("Thermal receipt printed via ESC/POS!", "success");
      onPrinted?.();
    } catch (err: any) {
      setPrinterStatus(`Thermal printer error: ${err?.message || "Permission denied or disconnected"}`);
      pushToast("Thermal printer unavailable or permission cancelled", "error");
    } finally {
      setPrinting(false);
    }
  };

  const handleNetworkEscPos = async () => {
    setPrinting(true);
    try {
      const res = await api.post(
        `/printing/receipts/${receipt.order_number}/print`,
        {
          printer_target: "network_escpos",
          paper_width: paperSize === "58mm" ? "58mm" : "80mm",
          is_reprint: receipt.reprint_count > 0,
        },
        { headers: guestHeaders }
      );
      if (res.data.status === "failed") {
        setLastFailedJobId(res.data.id);
        setPrinterStatus(`Failed: ${res.data.error_message}`);
        pushToast(res.data.error_message || "Network thermal printer unreachable", "error");
      } else {
        setLastFailedJobId(null);
        setPrinterStatus("Printed via Network ESC/POS");
        pushToast("Printed on network thermal printer", "success");
      }
      onPrinted?.();
    } catch (err) {
      pushToast(getApiError(err, "Network print error"), "error");
    } finally {
      setPrinting(false);
    }
  };

  const handleRetryFailed = async () => {
    if (!lastFailedJobId) return;
    try {
      const res = await api.post(`/printing/jobs/${lastFailedJobId}/retry`);
      setPrinterStatus(`Retry #${res.data.retry_count}: ${res.data.status} ${res.data.error_message || ""}`);
    } catch (err) {
      pushToast(getApiError(err), "error");
    }
  };

  const widthClass =
    paperSize === "58mm"
      ? "max-w-[260px] print-receipt-58mm text-xs"
      : paperSize === "80mm"
      ? "max-w-[340px] print-receipt-80mm text-xs"
      : "max-w-[640px] print-receipt-a4 text-sm";

  return (
    <div className="space-y-4">
      <div className="no-print flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-600">Format:</span>
          {(["58mm", "80mm", "a4"] as const).map((sz) => (
            <button
              key={sz}
              type="button"
              onClick={() => {
                setPaperSize(sz);
                setPrinterPrefs(sz, autoPrintPos);
              }}
              className={`rounded-lg px-2.5 py-1 text-xs font-bold uppercase ${
                paperSize === sz ? "bg-slate-900 text-white" : "bg-white text-slate-700 border border-slate-200"
              }`}
            >
              {sz}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" onClick={handleBrowserPrint} disabled={printing}>
            <Printer className="h-3.5 w-3.5" /> {receipt.reprint_count > 0 ? "Reprint Slip" : "Print Receipt"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => handleDownloadPdf("a4")}>
            <Download className="h-3.5 w-3.5" /> A4 PDF
          </Button>
          <Button size="sm" variant="outline" onClick={() => handleDownloadPdf("80mm")}>
            <Download className="h-3.5 w-3.5" /> 80mm PDF
          </Button>
          <Button size="sm" variant="outline" onClick={() => handleDownloadPdf("58mm")}>
            <Download className="h-3.5 w-3.5" /> 58mm PDF
          </Button>
          <Button size="sm" variant="outline" onClick={handleUsbEscPos} disabled={printing}>
            <Usb className="h-3.5 w-3.5" /> USB/Serial Thermal
          </Button>
          {allowStaffReprint && (
            <Button size="sm" variant="outline" onClick={handleNetworkEscPos} disabled={printing}>
              <Wifi className="h-3.5 w-3.5" /> LAN ESC/POS
            </Button>
          )}
          {lastFailedJobId && (
            <Button size="sm" variant="danger" onClick={handleRetryFailed}>
              <RefreshCw className="h-3.5 w-3.5" /> Retry Print
            </Button>
          )}
        </div>
      </div>

      <div className="no-print flex items-center justify-between text-xs text-slate-500 px-1">
        <span>Printer Status: {printerStatus}</span>
        {receipt.reprint_count > 0 && <Badge tone="amber">Reprint Count: {receipt.reprint_count}</Badge>}
      </div>

      {/* Actual Printable Slip */}
      <div className={`mx-auto rounded-xl border border-slate-300 bg-white p-5 font-mono text-slate-900 shadow-md ${widthClass}`}>
        <div className="text-center space-y-0.5">
          <div className="mb-1.5 flex justify-center">
            <BrandLogo size="sm" />
          </div>
          <div className="text-base font-extrabold tracking-wider">{receipt.brand}</div>
          <div className="font-bold uppercase">{receipt.college_name}</div>
          <div className="font-semibold uppercase">{receipt.canteen_name}</div>
          {receipt.canteen_location && <div className="text-[11px] text-slate-600">{receipt.canteen_location}</div>}
          {receipt.canteen_contact && <div className="text-[11px] text-slate-600">Tel: {receipt.canteen_contact}</div>}
          {(receipt.is_reprint || receipt.reprint_count > 0) && (
            <div className="mt-1 inline-block rounded border border-red-600 px-2 py-0.5 text-[11px] font-extrabold text-red-600">
              {receipt.reprint_label || `REPRINT #${Math.max(1, receipt.reprint_count)}`}
            </div>
          )}
        </div>

        <hr className="my-3 border-dashed border-slate-400" />

        <div className="space-y-0.5 text-[11px]">
          <div className="flex justify-between">
            <span>ORDER NO:</span>
            <span className="font-bold">{receipt.order_number}</span>
          </div>
          <div className="flex justify-between">
            <span>RECEIPT:</span>
            <span>{receipt.receipt_number}</span>
          </div>
        </div>

        <div className="my-3 flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 py-3">
          <div className="text-[11px] font-bold tracking-widest text-slate-500">PICKUP TOKEN</div>
          <div className="my-1 text-4xl font-black tracking-wider text-slate-900">{receipt.pickup_token}</div>
          <div className="rounded-lg bg-white p-2 border border-slate-200">
            <QRCodeSVG value={receipt.qr_payload} size={paperSize === "58mm" ? 110 : 136} level="M" includeMargin={false} />
          </div>
        </div>

        <hr className="my-3 border-dashed border-slate-400" />

        <div className="space-y-0.5 text-[11px]">
          <div className="flex justify-between">
            <span>CUSTOMER:</span>
            <span className="font-semibold">
              {receipt.customer_name} ({receipt.customer_type_label})
            </span>
          </div>
          {receipt.customer_mobile_masked && (
            <div className="flex justify-between">
              <span>MOBILE:</span>
              <span>{receipt.customer_mobile_masked}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span>DATE / TIME:</span>
            <span>
              {receipt.order_date} {receipt.order_time}
            </span>
          </div>
          <div className="flex justify-between">
            <span>COUNTER:</span>
            <span className="font-bold">{receipt.counter_name}</span>
          </div>
          <div className="flex justify-between">
            <span>TYPE / EST PICKUP:</span>
            <span>
              {receipt.order_type.toUpperCase()} / {receipt.estimated_pickup_time}
            </span>
          </div>
        </div>

        <hr className="my-3 border-dashed border-slate-400" />

        <div className="mb-1.5 font-bold uppercase text-[11px]">ORDERED ITEMS</div>
        <div className="space-y-2">
          {receipt.items.map((item, idx) => (
            <div key={idx} className="text-[11px] leading-snug">
              <div className="flex justify-between font-bold">
                <span>
                  {idx + 1}. {item.item_name}
                  {item.variant_name ? ` (${item.variant_name})` : ""}
                </span>
                <span>
                  {receipt.currency_symbol}
                  {item.line_subtotal}
                </span>
              </div>
              <div className="pl-3 text-slate-600">
                Qty: {item.quantity} × {receipt.currency_symbol}
                {item.unit_price}
              </div>
              {item.customizations.map((cust, cIdx) => (
                <div key={cIdx} className="flex justify-between pl-3 text-slate-600">
                  <span>
                    {cust.option_name}: {cust.option_value}
                  </span>
                  <span>
                    {Number(cust.total_price) > 0
                      ? `${receipt.currency_symbol}${cust.total_price}`
                      : "Included"}
                  </span>
                </div>
              ))}
              {item.special_instructions && (
                <div className="pl-3 italic text-slate-500">Note: {item.special_instructions}</div>
              )}
            </div>
          ))}
        </div>

        <hr className="my-3 border-dashed border-slate-400" />

        <div className="space-y-1 text-[11px]">
          <div className="flex justify-between">
            <span>SUBTOTAL</span>
            <span>
              {receipt.currency_symbol}
              {receipt.subtotal_amount}
            </span>
          </div>
          {Number(receipt.discount_amount) > 0 && (
            <div className="flex justify-between">
              <span>DISCOUNT</span>
              <span>
                -{receipt.currency_symbol}
                {receipt.discount_amount}
              </span>
            </div>
          )}
          {Number(receipt.tax_amount) > 0 && (
            <div className="flex justify-between">
              <span>TAX</span>
              <span>
                {receipt.currency_symbol}
                {receipt.tax_amount}
              </span>
            </div>
          )}
          <div className="flex justify-between border-t border-slate-300 pt-1 text-sm font-black">
            <span>TOTAL PAID</span>
            <span>
              {receipt.currency_symbol}
              {receipt.total_paid}
            </span>
          </div>
          {Number(receipt.tax_amount) === 0 && (
            <div className="text-[10px] text-slate-500 text-center pt-0.5">
              Listed prices inclusive of applicable statutory taxes.
            </div>
          )}
          <div className="flex justify-between pt-1">
            <span>PAYMENT STATUS</span>
            <span className="font-bold text-emerald-700">{receipt.payment_status}</span>
          </div>
          <div className="flex justify-between">
            <span>METHOD / REF</span>
            <span>
              {receipt.payment_method.toUpperCase()} / {receipt.payment_reference}
            </span>
          </div>
        </div>

        <hr className="my-3 border-dashed border-slate-400" />

        <div className="text-center text-[11px] space-y-1">
          <div className="font-bold">STATUS: {receipt.order_status}</div>
          <div className="font-semibold">
            PICKUP: {receipt.canteen_name} / {receipt.counter_name}
          </div>
          <div className="pt-1 text-[10px] text-slate-600 space-y-0.5">
            {receipt.pickup_instructions.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
          <div className="pt-2 font-bold">THANK YOU FOR ORDERING!</div>
        </div>
      </div>
    </div>
  );
};
