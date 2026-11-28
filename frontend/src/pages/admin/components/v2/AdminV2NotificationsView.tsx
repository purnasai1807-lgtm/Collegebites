import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCheck, Megaphone } from "lucide-react";
import { api, getApiError } from "../../../../api/client";
import { Badge, Button, useToast } from "../../../../components/ui/Primitives";
import { PromotionsTab } from "../PromotionsSystemTab";
import { V2PanelHeader } from "./AdminV2Widgets";

interface AdminV2NotificationsViewProps {
  activeCanteenId: string;
}

export const AdminV2NotificationsView: React.FC<AdminV2NotificationsViewProps> = ({ activeCanteenId }) => {
  const { pushToast } = useToast();
  const [subTab, setSubTab] = useState<"alerts" | "announcements">("alerts");

  const { data: notifications = [], refetch } = useQuery<any[]>({
    queryKey: ["notifications-my"],
    staleTime: 15_000,
    queryFn: async () => (await api.get("/notifications/my")).data,
  });

  const markAllRead = async () => {
    try {
      await api.post("/notifications/read-all");
      pushToast("All notifications marked as read", "success");
      refetch();
    } catch (err) {
      pushToast(getApiError(err, "Failed to update notifications"), "error");
    }
  };

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  return (
    <div className="space-y-6">
      <V2PanelHeader
        title="Notifications & Campus Announcements"
        subtitle="System alerts, order updates, and broadcast announcements across CollegeBites."
        rightSlot={
          <div className="flex items-center gap-1 rounded-xl border border-[#368BEA]/25 bg-[#0B1929] p-1">
            <button
              type="button"
              onClick={() => setSubTab("alerts")}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subTab === "alerts" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              <Bell className="h-3.5 w-3.5" /> Admin Feed ({unreadCount} unread)
            </button>
            <button
              type="button"
              onClick={() => setSubTab("announcements")}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                subTab === "announcements" ? "bg-[#20C5D8] text-[#071321]" : "text-[#9BAFC2] hover:text-[#F4F8FC]"
              }`}
            >
              <Megaphone className="h-3.5 w-3.5" /> Banners &amp; Announcements
            </button>
          </div>
        }
      />

      {subTab === "announcements" ? (
        <PromotionsTab activeCanteenId={activeCanteenId} />
      ) : (
        <div className="rounded-2xl border border-[#368BEA]/20 bg-[#102438] p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-extrabold text-[#F4F8FC]">
              Recent Operational Alerts ({notifications.length})
            </div>
            {unreadCount > 0 && (
              <Button size="sm" variant="outline" onClick={markAllRead}>
                <CheckCheck className="h-3.5 w-3.5" /> Mark All Read
              </Button>
            )}
          </div>

          {notifications.length === 0 ? (
            <div className="py-10 text-center text-xs text-[#9BAFC2]">No notifications in your inbox yet.</div>
          ) : (
            <div className="space-y-2 max-h-[520px] overflow-y-auto">
              {notifications.map((n: any) => (
                <div
                  key={n.id}
                  className={`rounded-xl border p-3.5 flex flex-wrap items-start justify-between gap-2 text-xs ${
                    n.is_read
                      ? "border-[#368BEA]/15 bg-[#0B1929]/70"
                      : "border-[#20C5D8]/40 bg-[#153149]"
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2 font-bold text-[#F4F8FC]">
                      <span>{n.title}</span>
                      {!n.is_read && <Badge tone="blue">NEW</Badge>}
                      {n.event_type && <Badge tone="slate">{n.event_type}</Badge>}
                    </div>
                    <p className="mt-1 text-[#9BAFC2]">{n.message}</p>
                  </div>
                  <span className="font-mono text-[10px] text-[#9BAFC2]">
                    {n.created_at ? new Date(n.created_at).toLocaleString("en-IN") : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
