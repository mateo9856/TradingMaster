import { requestData } from "@/shared/http";
import type { Currencies } from "./currency-types";

export const currencyApi = {
  /** Currencies prices can be shown in, with their latest ECB rate. Public. */
  currencies(): Promise<Currencies> {
    return requestData<Currencies>("/api/v1/currencies");
  },

};
