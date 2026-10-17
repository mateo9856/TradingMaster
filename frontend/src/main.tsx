import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "@/lib/auth";
import { CurrencyProvider } from "@/lib/currency-context";
import "@/lib/i18n";
import { removeServerSeoTags } from "@/lib/seo-tags";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// The server's head tags are for the first response only; pages render their own from here on.
removeServerSeoTags();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <CurrencyProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </CurrencyProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
