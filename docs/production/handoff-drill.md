# Handoff Drill and Usability Test

Two exercises the plan requires before the system is considered handed over. Both are performed
with people, not by reading. Neither can be marked done from a code review.

Record results in [§3](#3-results-log) — an unrecorded drill is an untested one.

---

## 1. Usability test (non-technical operator)

**Purpose:** find where the interface confuses someone who did not build it, then fix that friction.

**Who:** a person who will actually use the system, has not seen it before, and has no technical
background. Not a developer. Not someone who watched a demo.

**Setup:** a working deployment with at least one active model and some historical data. Give them
[Panduan Operator](panduan-operator.md) and nothing else.

### Rules for the observer

1. **Do not help.** The moment you explain something, you have destroyed the finding.
2. Ask them to think aloud.
3. Write down the *first* thing they try, not just what eventually worked.
4. Record every hesitation over ~10 seconds. Hesitation is friction even when they recover.
5. Stop a task after 5 minutes of being stuck. That is a failed task, and it is data, not a
   judgement of the person.

### Tasks

| # | Task | Passes when |
|---|---|---|
| 1 | Sign in | Reaches the overview unaided |
| 2 | Predict fuel for one operation (35 km, transport + 2h lifting) | Reads the **recommended allocation**, not the raw estimate |
| 3 | Say what the number means | Says "fuel to prepare", not "fuel that will be used" |
| 4 | Predict for 20 operations from a spreadsheet | Finds and uses the template |
| 5 | Fix a rejected row and re-upload | Understands the rejection message unaided |
| 6 | Record actual fuel for a completed operation | Finds the page unaided |
| 7 | Say whether monitoring is currently healthy | Reads Kesehatan Sistem correctly |
| 8 | Say what a drift warning means and what to do | Does **not** conclude the app is broken |

Task 3 is the one that matters most. An operator who believes the number is measured consumption
will mis-plan, and no amount of accuracy fixes that.

### After

For each failure or hesitation, decide: **change the interface**, **change the guide**, or
**accept and document**. Prefer changing the interface — a guide that has to explain a confusing
screen is a workaround, not a fix. Then re-test the changed tasks with a *different* person.

---

## 2. Handoff drill (technical owner)

**Purpose:** confirm the person taking over can run and recover the system without its builder.

**Who:** the incoming technical owner, working alone. The builder observes silently and answers
nothing that [the runbook](recovery-runbook.md) already covers — if they have to ask, the runbook
has a gap, and that gap is the finding.

**Setup:** a deployment that is *not* production, restored from a real backup.

| # | Exercise | Passes when |
|---|---|---|
| 1 | Bring the stack up from `compose.prod.yaml` | All services healthy; only 80/443 published |
| 2 | Confirm HTTPS works and the certificate is valid | Loads over HTTPS without warnings |
| 3 | Complete one prediction and one bulk import | Both succeed |
| 4 | Record actual fuel, then read the performance report | Understands "insufficient labels" if shown |
| 5 | Upload a valid model package | Accepted, retained, **and the active model is unchanged** |
| 6 | Upload a deliberately broken package | Rejected with a readable reason; active model untouched |
| 7 | Activate the uploaded package | Prediction afterwards comes from the new version |
| 8 | Force an activation failure (corrupt a retained artefact) | Refused; **previous model still serving** |
| 9 | Roll back to the previous version | Restored, and an audit record exists |
| 10 | Issue an agent credential, call `/mcp`, revoke it, call again | Works, then 401 |
| 11 | Confirm the MCP call appears in the audit trail | Caller, tool, and outcome all present |
| 12 | Run monitoring manually and confirm an alert is delivered | Alert arrives with its remediation text |
| 13 | Restore from backup on a clean machine | All four post-restore checks pass |
| 14 | Find, in the runbook alone, what to do about a leaked credential | Reaches §9 without help |

### Exercise 8 in detail

This is the one people skip, and it is the one that protects production:

```bash
docker compose -f compose.prod.yaml exec app sh -c \
  'printf tampered >> /data/model-packages/<version>/model.skops'
```

Then activate that version from **Pengelolaan Model**. Expected: refusal naming the failing
member, and the previously active model still serving predictions. Retained bytes are re-verified
against the manifest at activation time precisely so this cannot slip through.

Restore the artefact afterwards, or re-upload the package.

### Exercise 13 in detail

Do not shortcut this by restoring onto the machine that made the backup. The point is to prove the
backup is self-sufficient: a clean machine, the private `age` key from wherever the operator keeps
it, and nothing borrowed from the source VM.

If the key cannot be found, **that is the drill's most important finding** — an encrypted backup
whose key is lost is not a backup.

---

## 3. Results log

Copy this block per run.

```
Date:
Exercise set:      [ ] usability   [ ] handoff
Participant role:
Observer:

Tasks attempted:        /
Tasks passed:           /
Failures (task # and what they did instead):

Hesitations over 10s (task # and where):

Runbook gaps found:

Decisions (interface change / guide change / accepted):

Re-test scheduled for:
```

### Completion

The plan's acceptance criteria are met when:

- every usability task passes with a participant who did **not** take the earlier round, and
- every handoff exercise passes with the incoming owner working alone, and
- every gap found has been either fixed or explicitly accepted and written down.

A drill with unrecorded findings does not count as passed.

---

## 4. Status

| Exercise set | Status |
|---|---|
| Usability test | **Not yet performed.** Requires a non-technical participant. |
| Handoff drill | **Not yet performed.** Requires an incoming technical owner and a non-production deployment. |

These two are the only Phase 6 items that cannot be completed by writing code, and they are
deliberately left open rather than marked done. Exercises 5–12 have each been verified individually
against a running server during implementation; what has **not** happened is a person other than
the builder performing them end to end.
