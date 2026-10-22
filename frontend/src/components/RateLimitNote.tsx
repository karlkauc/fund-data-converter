import { useI18n } from "../lib/i18n";
import { useLimitsText, windowName } from "../lib/rateLimit";
import type { RateWindow } from "../types";

function formatWait(seconds: number): string {
  return seconds < 60 ? `${seconds} s` : `${Math.ceil(seconds / 60)} min`;
}

/** The visitor's rate limit (GET /api/limits, then the report of each conversion). */
export function RateLimitNote({ windows }: { windows: RateWindow[] }) {
  const { t } = useI18n();
  const limitsText = useLimitsText();
  if (!windows.length) return null;
  const limits = limitsText(windows);
  const exhausted = windows.filter((w) => w.remaining <= 0);
  if (exhausted.length) {
    const wait = Math.max(...exhausted.map((w) => w.resetSeconds), 1);
    return (
      <p role="status" className="text-center text-xs font-medium text-amber-700 dark:text-amber-400">
        {t("rateLimitExhausted", { limits, wait: formatWait(wait) })}
      </p>
    );
  }
  const left = windows
    .map((w) => t("rateLeftIn", { n: w.remaining, window: windowName(t, w.window) }))
    .join(", ");
  return (
    <p className="text-center text-xs text-slate-500 dark:text-slate-400" data-testid="rate-limit">
      {t("rateLimitLine", { limits, left })}
    </p>
  );
}
