# Turn-final question pinning + clarification relay (LAAM /api/chat)

Decision record for `src/lib/chat/backstop-notice.ts` — why the turn-final nudges say what
they say. Measured on the 12-question Michael Pharmacy Chain set, 2026-08-05,
`gpt-oss-120b`/BytePlus. Related: `mem:checkpoint/web-dev-2026-08-05-tool-loop-round-cap`.

## The three things a turn-final nudge must get right

**1. Pin the question — on BOTH exit paths.**
In a long thread the model answers a *previous* turn's topic. Measured: Q12 ("after-hours
overrides") came back about cash-drawer shortages (Q9's topic) in text mode on a force-stop,
and again in Larvis mode on a **natural completion with zero backstops**. So the nudge that
only runs on backstop (`synthNudge`) is not enough — `restateQuestion` covers the natural path.
Both interpolate the literal question. Applied only when the turn ran tools: a chitchat turn
has no tool results to drift among, and appending a turn there moves the request shape that
`route.test.ts`'s `bareTurnFetch` call-count assertions pin.

**2. Never claim the data is sufficient on a force-stop.**
The original SYNTH_NUDGE opened with "Đã đủ dữ liệu" — false by definition when the loop was
cut short, and it pushes a confident answer built on whatever partial rows survived eviction.

**3. Carve out clarifying questions — THE NON-OBVIOUS ONE.**
Telling the model "if the data doesn't answer this, say so plainly" (added for #1) caused a
NEW failure: DAAB returned `status=clarification_needed` with the clarifying question attached
(`internal/handler/ai_query.go` adds a `clarification` field; the tool description at
`internal/bridge/schema.go:1833` says to relay it), and the model reported "chưa có dữ liệu"
instead — **silently defeating DAAB's entire ask-back feature**. Both nudges now carry an
explicit exception: a clarifying question must be relayed to the user in plain language
(explain the meaning, do not recite table/column names), never reported as missing data.

Verified after the fix: Q12 relays numbered options in plain Vietnamese in BOTH modes — which
is the correct outcome, since the demo doc itself calls Q12 the most ambiguous of the twelve.

## Generalizable lesson
An instruction added to fix one failure mode ("say plainly when you can't answer") can disable
a feature living in a different layer ("relay the connector's clarifying question"). When a
nudge tells the model how to behave on missing data, enumerate what "missing" does NOT cover.

## Voice-mode carve-out
`loopTruncatedNotice(lang, mode)` returns "" for `mode === "voice"`: on /constellation the
reply is spoken, and TTS reads the "(stopped after many tool steps)" parenthetical aloud as if
it were part of the answer. Same spoken-register precedent as the currency formatting in
`lib/chat/voice.ts`. Text keeps it (Rule 12).

## Known drift
The Ollama tool-loop path has neither nudge (pre-existing for `synthNudge`). Ollama is not
running in this deployment (BytePlus is the cloud-first default), so the change was kept to
the measured, verifiable path rather than shipped blind.
