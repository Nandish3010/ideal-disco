import { useEffect } from "react";
import LangToggle from "../i18n/LangToggle.jsx";
import { getLang, has, t, useLang } from "../i18n/index.js";

// Page chrome: skip link, header (h1 + nav + language toggle) and the one <main>. Pages render inside it.
export default function Shell({ routes, path, title, Page }) {
  const lang = useLang();
  // route names come from nav.<path>; a route without a dictionary entry keeps its English name
  const label = (p, name) =>
    has(`nav.${p.slice(1) || "home"}`) ? t(`nav.${p.slice(1) || "home"}`) : name;
  const heading = path === "/" ? t("app.title") : label(path, title);
  useEffect(() => {
    document.documentElement.lang = getLang();
    document.title = path === "/" ? t("app.title") : `${heading} · ${t("app.title")}`;
  }, [lang, path, heading]);
  return (
    <>
      <a className="skip" href="#main">
        {t("a11y.skip")}
      </a>
      <header className="bar">
        <h1>{heading}</h1>
        <nav aria-label={t("a11y.screens")}>
          {Object.entries(routes).map(([p, [name]]) => (
            <a key={p} href={p} aria-current={p === path ? "page" : undefined}>
              {label(p, name)}
            </a>
          ))}
        </nav>
        <LangToggle />
      </header>
      <main id="main" tabIndex={-1}>
        <Page />
      </main>
    </>
  );
}
