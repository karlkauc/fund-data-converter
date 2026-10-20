import clsx from "clsx";
import { useRef, useState, type DragEvent } from "react";
import { useI18n } from "../lib/i18n";

interface Props {
  accept: string;
  hint: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}

export function DropZone({ accept, hint, disabled, onFile }: Props) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && !disabled) onFile(file);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      data-testid="dropzone"
      className={clsx(
        "panel flex flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-10 text-center transition-colors md:py-14",
        over ? "border-accent bg-blue-50 dark:bg-blue-950/40" : "border-slate-300 dark:border-slate-700",
      )}
    >
      <div className="text-3xl text-accent dark:text-accent-dark" aria-hidden>
        ⬆
      </div>
      <p className="text-slate-700 dark:text-slate-200">
        {t("dropTitle")}{" "}
        <button
          type="button"
          className="btn btn-primary ml-1"
          disabled={disabled}
          onClick={() => input.current?.click()}
        >
          {t("chooseFile")}
        </button>
      </p>
      <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
