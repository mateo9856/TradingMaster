/**
 * The server writes each page's title, description, canonical, hreflang, Open
 * Graph and JSON-LD into the HTML it sends, marked `data-seo` (app/seo.py) —
 * that is what crawlers without JavaScript and link previews read. Once the app
 * runs, every page renders its own (src/components/Seo.tsx) and keeps them
 * right across client-side navigation, so the server's copies are removed
 * first rather than left behind as duplicates.
 */
export function removeServerSeoTags(root: ParentNode = document): void {
  root.querySelectorAll("[data-seo]").forEach((node) => node.remove());
}
