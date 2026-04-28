/**
 * Tiny in-house toast — supports a single concurrent message.
 *
 * Built lightweight because Phase-1 only needs the "Coming in Phase X"
 * stub announcements. A more featureful provider (queue, severities,
 * action buttons) lands later if more screens demand it.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastState = { message: string; key: number } | null;

type ToastContextValue = {
  showToast: (message: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_TIMEOUT_MS = 3500;

export function ToastProvider({
  children,
}: {
  children: ReactNode;
}): React.JSX.Element {
  const [state, setState] = useState<ToastState>(null);
  const counterRef = useRef(0);

  const showToast = useCallback((message: string) => {
    counterRef.current += 1;
    setState({ message, key: counterRef.current });
  }, []);

  useEffect(() => {
    if (state === null) return;
    const handle = setTimeout(() => {
      setState(null);
    }, TOAST_TIMEOUT_MS);
    return () => clearTimeout(handle);
  }, [state]);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {state ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="toast"
          className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 transform"
        >
          <div className="pointer-events-auto rounded-lg bg-bg-surface-raised px-4 py-3 text-sm text-text-primary shadow-lg ring-1 ring-border-default">
            {state.message}
          </div>
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (ctx === null) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}
