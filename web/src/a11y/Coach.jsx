import { useState } from "react";
import { store } from "../ui.jsx";
import { t } from "../i18n/index.js";

// First visit per role: three short tips, dismissed with one tap and remembered in localStorage.
// roles: vehicle | cop | hospital; copy lives in the dictionaries as coach.<role>.1..3
export default function Coach({ role }) {
  const key = `coach_${role}`;
  const [open, setOpen] = useState(() => store.get(key) !== "1");
  if (!open) return null;
  return (
    <aside className="coach" aria-label={t("coach.title")}>
      <b>{t("coach.title")}</b>
      <ol>
        {[1, 2, 3].map((n) => (
          <li key={n}>{t(`coach.${role}.${n}`)}</li>
        ))}
      </ol>
      <button
        type="button"
        onClick={() => {
          store.set(key, "1");
          setOpen(false);
        }}
      >
        {t("coach.dismiss")}
      </button>
    </aside>
  );
}
