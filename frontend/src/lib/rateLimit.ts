import type { RateWindow } from "../types";
import { useI18n, type MessageKey } from "./i18n";

const WINDOW_NAME: Record<string, MessageKey> = { minute: "rateWindowMinute", hour: "rateWindowHour" };

type Translate = ReturnType<typeof useI18n>["t"];

export function windowName(t: Translate, window: string): string {
  const key = WINDOW_NAME[window];
  return key ? t(key) : window;
}

/** "20/minute, 200/hour" in the current language. */
export function useLimitsText(): (windows: RateWindow[]) => string {
  const { t } = useI18n();
  return (windows) => windows.map((w) => `${w.limit}/${windowName(t, w.window)}`).join(", ");
}
