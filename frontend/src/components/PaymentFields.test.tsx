import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { PaymentFields } from "./PaymentFields";
import type { PaymentSelection, PaymentAccounts } from "@/lib/trading";
import { PAYMENT_ACCOUNTS } from "@/test/handlers";
import { renderApp } from "@/test/render";

function Methods() {
  const [value, setValue] = useState<PaymentSelection>({ payment_method: "credits" });
  return <PaymentFields value={value} onChange={setValue} accounts={PAYMENT_ACCOUNTS as PaymentAccounts} walletBalance="10000.00000000" />;
}

describe("payment cards", () => {
  it("uses native keyboard navigation and shows the selected account", async () => {
    renderApp(<Methods />);
    const wallet = screen.getByRole("radio", { name: "TradingMaster funds" });
    await userEvent.click(wallet);
    expect(wallet).toBeChecked();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Payment card" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Debit card" })).toBeChecked();
    expect(screen.getByText("Available simulated funds: 10000.00 USD")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "PayPal" })).toBeChecked();
    expect(screen.queryByRole("group", { name: "Card type" })).not.toBeInTheDocument();
  });

  it("disables method changes while submitting", async () => {
    const changed = vi.fn();
    renderApp(<PaymentFields value={{ payment_method: "credits" }} onChange={changed} disabled />);
    const card = screen.getByRole("radio", { name: "Payment card" });
    expect(card).toBeDisabled();
    await userEvent.click(card);
    expect(changed).not.toHaveBeenCalled();
  });
});
