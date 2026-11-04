import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/features/auth/auth";
import { monitoringApi } from "./api";

export function useMonitoring() {
  const { user } = useAuth();
  const client = useQueryClient();
  return { user, key: ["monitoring", user?.id],
    refresh: () => client.invalidateQueries({ queryKey: ["monitoring", user?.id] }) };
}

export function useMonitoringSettings() {
  const { user, key } = useMonitoring();
  return useQuery({ queryKey: [...key, "settings"], queryFn: monitoringApi.settings, enabled: Boolean(user), retry: false,
    refetchInterval: 30_000, refetchIntervalInBackground: false });
}

export function useMonitoringAlerts(offset = 0) {
  const { user, key } = useMonitoring();
  return useQuery({ queryKey: [...key, "alerts", offset], queryFn: () => monitoringApi.alerts(offset), enabled: Boolean(user),
    retry: false, refetchInterval: 30_000, refetchIntervalInBackground: false });
}
