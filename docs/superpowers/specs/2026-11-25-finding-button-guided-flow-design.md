# Workflows: a guided path to "a button on the findings page"

Owner-approved 2026-11-25 ("làm A và B luôn đi"; flow: "Dẫn từng bước"). A, the clearer copy on the AI toggle, shipped first.

## Why

The AI-builder toggle "This workflow runs from a finding" was hard to understand and easy to miss.

- It is off by default for a new workflow and saves nothing by itself.
- The real button setup lives elsewhere: on the org copy's detail page, after "Add to the organization toolkit".
- A user who never ticks the toggle gets a graph that cannot become a finding action, and only finds out later.

## Goal

An owner/admin who wants a finding button is told once, at the start, and is then led step by step:

1. **New workflow → pick a kind (owner/admin only).**
   - The choices are "Runs on a schedule or by hand" and "A button on the findings page".
   - Members keep today's one-click create.
2. **Picking the button kind** opens the editor with the AI toggle already on (`/workflows/<id>/edit?for=finding`).
3. **On the personal workflow's detail page,** when the workflow is meant for a finding, a 2-step guide replaces today's one-line hint:
   1. Add it to the organization toolkit, with a button that opens the existing share dialog.
   2. Set up the button on the organization copy.
4. **After a successful share** of such a workflow, the share dialog offers "Set up the finding button". It links to the org copy's detail page, at the finding-action section.
5. **On the org copy,** when the workflow is meant for a finding and has no finding-action config yet, the card opens pre-filled:
   - "Let people run this…" is ticked;
   - both button labels are the workflow name.
   - A note says nothing is live until Save. The admin still reviews and saves: no silent activation for the whole organization.

## Approach

- "Meant for a finding" is read from the graph itself. It is true when any `{{trigger.items…}}` or `{{trigger.finding…}}` reference is present. There is no new column and no migration, and it works for workflows built before this change.
  - Helper: `isFindingIntentGraph(graph)` in a new client-safe `src/lib/workflow/finding-intent.ts`.
- The chooser is a small dialog in `WorkflowsClient`, reusing the existing create call. The list page passes `canManagePresets`.
- The editor takes `startInFindingMode` from the edit page (the `for=finding` query). It turns the AI toggle on once at load when the workflow has no finding-action config.
- `ShareToPresetDialog` takes an optional `findingIntent`. On success with a `workflowId`, it shows the extra link `/workflows/<workflowId>#finding-action`.
- `FindingActionCard` takes an optional `suggest: { name }`, used only when the loaded config is null.
- Copy in vi/en/zh in the workflows dictionary.

## Non-goals

- Creating an org workflow directly from the chooser (option 2 was declined).
- Auto-saving a finding-action config.
- Changing the server-side gates (`findingActionGraphProblems`, the share checks, role checks).

## Verification

- Unit tests:
  - the intent helper;
  - the chooser (owner/admin see it, members do not, the button kind goes to `?for=finding`);
  - the editor starts with the toggle on;
  - the guide card;
  - the share dialog link;
  - the card pre-fill (and none when a config exists).
- `tsc`, `npm test`, `npm run build`.
- Browser walk-through on :3900: new → button kind → AI toggle on → save → guide → share → link → pre-filled card. Cancel before Save on the org copy.
