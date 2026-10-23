import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";
import { MarketsPage } from "./MarketsPage";

describe("market collection sources", () => {
  it("shows exchange brand names for crypto and stocks", async () => {
    renderApp(<MarketsPage />);
    const table = within(await screen.findByRole("table"));
    expect(table.getByText("Binance, Kraken")).toBeInTheDocument();
    expect(table.getByText("Yahoo Finance")).toBeInTheDocument();
    expect(table.queryByText("binance, kraken")).not.toBeInTheDocument();
    expect(table.queryByText("yahoo")).not.toBeInTheDocument();
  });
});
