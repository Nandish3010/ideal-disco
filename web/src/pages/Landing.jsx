import { BASE } from "../api.js";
import { t, tn } from "../i18n/index.js";
import { corridors } from "../data.js";
import { lead, savedRange, simulate } from "../replay.js";
import "../story.css";
import scenario from "../../../data/scenarios/blr-two-vehicles.json";

// The hero figures come from the same replay maths as /sim, computed once from the scenario, so the two always agree:
// the critical ambulance's own saving leads, the all-vehicle total and the 1-3 m/s drain range follow.
const SIM = simulate(scenario, corridors[scenario.corridor]);
const HERO = {
  n: (lead(SIM).saved_s / 60).toFixed(1),
  all: (SIM.saved_s / 60).toFixed(1),
  k: SIM.vehicles.length,
  range: savedRange(scenario, corridors[scenario.corridor]).map((m) => m.toFixed(1)),
};

const GEMINI = [1, 2, 3, 4, 5, 6, 7].map((n) => `landing.g${n}`);
const SCREENS = ["vehicle", "cop", "hospital", "control", "sim", "dispatch"];

export default function Landing() {
  const link = (href) => (
    <a className="inline" href={href}>
      {href}
    </a>
  );
  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-h">
        <h2 id="hero-h">{t("landing.hero_h")}</h2>
        <p className="lede">{t("landing.hero_lede")}</p>
        <p className="herofig">
          <b>{t("landing.saved", { n: HERO.n })}</b> {t("landing.saved_on")}{" "}
          <span className="muted">{t("landing.saved_note")}</span>
        </p>
        <p className="muted">
          {t("landing.saved_all", { k: HERO.k, n: HERO.all })}{" "}
          {t("landing.saved_range", { lo: HERO.range[0], hi: HERO.range[1] })}
        </p>
        <div className="ctas">
          <a className="cta" href="/sim?mode=replay&autoplay=1&speed=50">
            {t("landing.cta_demo")}
          </a>
          <a className="cta alt" href="/cop?sample=1">
            {t("landing.cta_cop")}
          </a>
          <a className="cta alt" href="/hospital?last=1">
            {t("landing.cta_handover")}
          </a>
          <a className="cta alt" href="/story">
            {t("landing.cta_story")}
          </a>
        </div>
      </section>

      <p className="lede">
        <b>{t("landing.problem_h")}</b> {t("landing.problem")}
      </p>
      <p className="lede">
        <b>{t("landing.fix_h")}</b> {t("landing.fix")}
      </p>

      <h2>{t("landing.h60")}</h2>
      <ol className="steps">
        <li>{tn("landing.step1", { link: link("/sim?mode=replay&speed=50") })}</li>
        <li>{tn("landing.step2", { link: link("/cop") })}</li>
        <li>{tn("landing.step3", { link: link("/hospital") })}</li>
      </ol>

      <h2>{t("landing.screens_h")}</h2>
      <nav className="screens" aria-label={t("landing.screens_aria")}>
        {SCREENS.map((k) => (
          <a key={k} href={`/${k}`}>
            <b>{t(`nav.${k}`)}</b> <span className="muted">{`/${k}`}</span>
            <div>{t(`landing.s_${k}`)}</div>
          </a>
        ))}
      </nav>

      <h2>{t("landing.gem_h")}</h2>
      <ul className="gem">
        {GEMINI.map((g) => (
          <li key={g}>{t(g)}</li>
        ))}
      </ul>

      <h2>{t("landing.limits_h")}</h2>
      <p className="banner">{t("landing.limits")}</p>
      <p className="muted">
        <a className="inline" href="https://github.com/Nandish3010/ideal-disco">
          {t("landing.repo")}
        </a>{" "}
        ·{" "}
        <a className="inline" href={`${BASE}/health`}>
          {t("landing.health")}
        </a>{" "}
        ·{" "}
        <a className="inline" href="/deck.pdf" target="_blank" rel="noreferrer">
          Submission deck (PDF)
        </a>{" "}
        <small>
          (
          <a className="inline" href="/deck.pptx">
            PowerPoint
          </a>
          )
        </small>
      </p>
    </div>
  );
}
