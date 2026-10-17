import { expect, it } from "vitest";

import { removeServerSeoTags } from "./seo-tags";

it("removes only the server-written head tags", () => {
  document.head.innerHTML = `
    <meta charset="UTF-8">
    <title data-seo>Server title</title>
    <meta data-seo name="description" content="x">
    <link data-seo rel="canonical" href="https://x/">
    <script data-seo type="application/ld+json">{}</script>
    <link rel="icon" href="/favicon.ico">`;

  removeServerSeoTags();

  expect(document.head.querySelectorAll("[data-seo]")).toHaveLength(0);
  expect(document.head.querySelector('link[rel="icon"]')).not.toBeNull();
  expect(document.head.querySelector("meta[charset]")).not.toBeNull();
});
