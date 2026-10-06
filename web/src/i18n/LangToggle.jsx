import { LANGS, getLang, setLang, t, useLang } from "./index.js";

// Three buttons in the top bar; the choice is saved in localStorage and English is the default.
export default function LangToggle() {
  useLang();
  return (
    <div className="lang" role="group" aria-label={t("a11y.language")}>
      {Object.entries(LANGS).map(([k, name]) => (
        <button
          key={k}
          type="button"
          lang={k}
          aria-pressed={getLang() === k}
          onClick={() => setLang(k)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}
