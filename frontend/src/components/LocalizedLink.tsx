/**
 * Links that stay in the current language: "/markets" becomes "/pl/markets"
 * while the UI is Polish. Every internal link goes through these, so a visitor
 * (or a crawler) never falls out of their language by clicking around.
 */

import { Link, NavLink } from "react-router-dom";
import type { LinkProps, NavLinkProps } from "react-router-dom";

import { useLanguage } from "@/hooks/useLanguage";
import { localizedPath } from "@/lib/i18n";

export function useLocalizedPath(): (path: string) => string {
  const language = useLanguage();
  return (path: string) => localizedPath(language, path);
}

export function LocalizedLink({ to, ...props }: Omit<LinkProps, "to"> & { to: string }) {
  const localize = useLocalizedPath();
  return <Link to={localize(to)} {...props} />;
}

export function LocalizedNavLink({ to, ...props }: Omit<NavLinkProps, "to"> & { to: string }) {
  const localize = useLocalizedPath();
  return <NavLink to={localize(to)} {...props} />;
}
