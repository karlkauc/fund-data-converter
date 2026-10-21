import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, sendFeedback } from "../lib/api";
import { EVENT_OPEN_FEEDBACK, type FeedbackContext } from "../lib/feedback";
import { useI18n } from "../lib/i18n";

type Status = { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string };

// Modal feedback form, opened from anywhere via openFeedback() (lib/feedback).
export function FeedbackDialog() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [context, setContext] = useState<FeedbackContext>({});
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const onOpen = (event: Event) => {
      setContext((event as CustomEvent<FeedbackContext>).detail ?? {});
      setStatus({ kind: "idle" });
      setOpen(true);
    };
    window.addEventListener(EVENT_OPEN_FEEDBACK, onOpen);
    return () => window.removeEventListener(EVENT_OPEN_FEEDBACK, onOpen);
  }, []);

  useEffect(() => {
    if (open) textareaRef.current?.focus();
  }, [open]);

  const close = useCallback(() => setOpen(false), []);

  const submit = useCallback(async () => {
    if (!message.trim()) return;
    setStatus({ kind: "sending" });
    try {
      await sendFeedback({
        message: message.trim(),
        email: email.trim() || undefined,
        page: window.location.pathname,
        direction: context.direction,
        tpt_version: context.tptVersion,
        error_detail: context.errorDetail?.slice(0, 255),
        website,
      });
      setStatus({ kind: "sent" });
      setMessage("");
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof ApiError ? err.message : String(err) });
    }
  }, [message, email, website, context]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 px-4 pt-4 md:pt-[10vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-title"
        className="panel max-h-[85dvh] w-full max-w-lg overflow-y-auto p-5 shadow-xl"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 id="feedback-title" className="text-base font-semibold">
              {t("feedbackTitle")}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{t("feedbackIntro")}</p>
          </div>
          <button type="button" className="btn" onClick={close} aria-label={t("feedbackClose")}>
            ✕
          </button>
        </div>

        {status.kind === "sent" ? (
          <div className="py-4">
            <p className="text-sm text-green-700 dark:text-green-400" role="status">
              {t("feedbackSent")}
            </p>
            <button type="button" className="btn btn-primary mt-4" onClick={close}>
              {t("feedbackClose")}
            </button>
          </div>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            {context.errorDetail && (
              <p className="mb-2 break-words font-mono text-xs text-slate-500 dark:text-slate-400">
                {t("feedbackErrorAttached")}: {context.errorDetail}
              </p>
            )}
            <label className="block text-sm">
              <span className="sr-only">{t("feedbackMessage")}</span>
              <textarea
                ref={textareaRef}
                required
                maxLength={4000}
                rows={5}
                placeholder={t("feedbackPlaceholder")}
                className="w-full rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-700 dark:bg-slate-950"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
            </label>
            <label className="mt-2 block text-sm">
              <span className="text-xs text-slate-500 dark:text-slate-400">{t("feedbackEmail")}</span>
              <input
                type="email"
                maxLength={254}
                className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-950"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            {/* Honeypot: hidden from people, filled by naive bots. */}
            <label className="hidden" aria-hidden="true">
              Website
              <input type="text" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
            </label>
            {status.kind === "error" && (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">
                {t("feedbackFailed")}: {status.message}
              </p>
            )}
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-[11px] text-slate-500 dark:text-slate-400">{t("feedbackPrivacy")}</p>
              <button type="submit" className="btn btn-primary" disabled={status.kind === "sending" || !message.trim()}>
                {status.kind === "sending" ? t("feedbackSending") : t("feedbackSend")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
