import { ApiError, NetworkError, request } from "@/shared/http";

export const systemApi = {
  health(): Promise<{ status: string }> {
    return request<{ status: string }>("/health");
  },

  /** Prometheus exposition format — parsed by ./metrics. */
  async metrics(): Promise<string> {
    const response = await fetch("/metrics").catch(() => {
      throw new NetworkError();
    });
    if (!response.ok) throw new ApiError(response.status, "Metrics are unavailable");
    return response.text();
  },

};
