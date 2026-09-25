# Checkpoint: claude — 2026-09-18 (AAAA_introduce default locale flip)

## What was done
User: "web intro AAAA set ngôn ngữ mặc định là tiếng Anh" (set AAAA's default
language to English). Flipped from Vietnamese-default to English-default —
the REVERSE of the deliberate decision made earlier this session (see round 1
checkpoint, which explicitly argued VI-default because the source product's
own metadata/distribution channel is Vietnamese). User overrode that decision;
treated it as their call, implemented fully, didn't re-litigate.

## Files changed
- `src/lib/i18n/index.ts`: `DEFAULT_LOCALE` "vi"->"en"; `detect()` now looks for
  `/vi` path / `?lang=vi` as the OVERRIDE (was `/en`/`?lang=en`); `urlForLocale`
  regex flipped to strip `/vi` prefix instead of `/en`.
- `index.html`: static `lang="en"` (was "vi"); title/description/og:title/
  og:description/twitter:* all swapped to the English strings (was Vietnamese
  static fallback); `og:locale` "vi_VN"->"en_US", added `og:locale:alternate
  content="vi_VN"` since the content is still genuinely Vietnamese-authored.
- `src/main.tsx`: comment corrected (`lang="en"` ships now, `?lang=vi` is the
  one that needs the pre-render sync call, not `?lang=en`).
- `src/lib/i18n/vi.ts` + `en.ts` header comments: IMPORTANT DISTINCTION now
  documented explicitly — `vi.ts` stays canonical for the TYPE SHAPE (content
  still originates in Vietnamese, `en: typeof vi`), separate from which locale
  is the RUNTIME DEFAULT (now `en`). These are two different questions; the
  file headers previously conflated them ("Vietnamese — the default, source of
  truth" as one claim). Don't re-conflate them in future edits.
- `README.md` `## Language` section rewritten to state EN-default + the
  canonical-vs-default distinction. Checked for other stale "Vietnamese is
  default" claims elsewhere in README — the "Vietnamese sets the typography"
  section was checked and does NOT need changes (its claims are about which
  language's letterforms are WIDER, a fact independent of which locale opens
  by default).
- CSS (`index.css` `:root` / `:root:lang(vi)`) needed NO changes — already
  keyed off the actual `document.documentElement.lang` value at runtime, not
  hardcoded to a "default" concept. Confirms good separation of concerns from
  the original build.

## Verified
- Fresh load at `/`: `lang="en"` at DOMContentLoaded (no VI flash), leading
  `.94` (Latin tier), English title, English H1/nav/panels — screenshot
  confirmed.
- `/?lang=vi`: `lang="vi"` at DOMContentLoaded, leading `1.24`, Vietnamese
  title/copy, locale toggle correctly shows "English" and points to `/`
  (strips the param since `en` is now `DEFAULT_LOCALE`).
- Build/typecheck/lint clean (same single inherited `useMediaQuery.ts`
  warning, unchanged all session).

## Follow-up — user: "anh chị" in the Contact CTA reads unprofessional
Grepped the WHOLE vi.ts (not just the screenshot) — found exactly 2 occurrences,
both in `cta.heading`/`cta.lead.rest`. Confirmed this is the ONLY place on the
entire page that directly addresses the reader in 2nd person at all — every
other section talks about "doanh nghiệp"/"hồ sơ"/"hệ thống" in the 3rd person,
impersonal register (verified: zero hits for "bạn"/"quý khách"/"quý vị"
anywhere else). Also checked: "anh chị" IS present in the ORIGINAL source
product's own vi.json (am-ai-agents) — this wasn't something I invented, it's
carried-over content the user is now asking to correct.

Fix: "anh chị" -> "doanh nghiệp bạn" (heading + first clause of lead.rest,
addressing the BUSINESS choosing the documents) / "bạn" alone (second clause of
lead.rest, addressing the PERSON attending the demo who sees the results — a
business can't "see" something, only a person can, so the two pronouns aren't
interchangeable within the same sentence). "Bạn" is the standard neutral/
professional address form in contemporary Vietnamese B2B/SaaS copy — light
enough for a CTA (where directly addressing the reader is expected and normal,
unlike body copy) without "anh chị"'s retail-customer-service register.
English `cta` copy already used neutral "your own documents" — no change needed
there.

Verified: heading now "Xem hệ thống chạy trên hồ sơ thật của doanh nghiệp bạn"
— wraps to 3 lines at 1440px, 5 lines at 320px, no overflow either width.
Build/typecheck/lint clean.

## Next steps / blockers
None. Not committed (repo rule: commit only when asked).
