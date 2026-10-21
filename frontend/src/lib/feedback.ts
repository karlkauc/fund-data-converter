import type { Direction } from "../types";

// What the feedback dialog attaches: never the file, only what the user was doing.
export interface FeedbackContext {
  direction?: Direction;
  tptVersion?: string;
  errorDetail?: string;
}

export const EVENT_OPEN_FEEDBACK = "tptfx:open-feedback";

// The converter keeps this up to date, so the footer link attaches the open conversion too.
let lastContext: FeedbackContext = {};

export function setFeedbackContext(context: FeedbackContext): void {
  lastContext = context;
}

export function openFeedback(context: FeedbackContext = {}): void {
  window.dispatchEvent(new CustomEvent(EVENT_OPEN_FEEDBACK, { detail: { ...lastContext, ...context } }));
}
