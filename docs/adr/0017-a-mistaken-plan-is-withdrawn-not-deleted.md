# ADR 0017: A mistaken plan is withdrawn, not deleted

## Status

Proposed

## Context

A double tap, a wrong vehicle or a plan made twice left an operation waiting for actual fuel
forever. It sat in every waiting list and in the Excel sheet of waiting operations, counted as
overdue on the monitoring page, and was offered as a precedent under later estimates - though
the operation never happened. There was no way to say so.

Deleting the operation would lose its estimate, its audit trail and possibly a code already
written on a slip, and would make the prediction history lie about what was planned.

## Decision

An operation can be **withdrawn** (cancelled), with a reason, until actual fuel is recorded
against it:

- **Kept, marked, never deleted.** The operation gains `cancelled_at`, `cancelled_by` and
  `cancel_reason`; its estimate and code stay. History shows it as *Dibatalkan*, the estimate
  page says when, by whom and why, and its code is shown struck through as "dibatalkan, jangan
  dipakai" - still readable, since it may already be on a slip.
- **A reason is required** (up to 256 characters) and is written to the audit trail as
  `operation_cancelled`, with the operation's code.
- **Only before actual fuel.** An operation with actual fuel recorded cannot be withdrawn: the
  day happened. Recording actual fuel against a withdrawn operation is refused, from the form,
  the sheet and the API alike.
- **Withdrawing twice changes nothing** and is recorded once.
- **A withdrawn plan counts for nothing downstream.** It leaves the waiting lists and the Excel
  sheet of waiting operations, is not overdue, is not a similar day under a new estimate, and is
  not among the recent operations drift is measured on.
- **Who.** Whoever may plan may withdraw (`CREATE_PREDICTION`): an operator corrects their own
  mistake without waiting for an administrator. The estimate page offers it as a quiet line at
  the bottom; `POST /api/v1/daily-operations/{code or id}/cancel` offers it to agents and scripts.

## Consequences

- Nothing is ever lost: a withdrawal can be read back, and the audit trail says who and why.
- There is no "undo": a plan withdrawn by mistake is planned again, and gets a new code.
- Every reader of operations that means "operations that happened" must leave withdrawn ones
  out. Those added since are the waiting lists, the overdue check, similar days and the drift
  sample; a new one must do the same.
