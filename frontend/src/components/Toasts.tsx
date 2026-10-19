import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { Tone } from './ui';

interface Toast {
  id: number;
  tone: Tone;
  text: ReactNode;
}
const ToastCtx = createContext<(tone: Tone, text: ReactNode) => void>(() => undefined);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const { t } = useTranslation();
  const push = useCallback((tone: Tone, text: ReactNode) => {
    const id = ++seq;
    setToasts((ts) => [...ts.slice(-4), { id, tone, text }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), tone === 'err' ? 10000 : 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite" aria-atomic="false">
        {toasts.map((ts) => (
          <div key={ts.id} className={`toast tone-${ts.tone}`} role={ts.tone === 'err' ? 'alert' : 'status'}>
            <div style={{ flex: 1 }}>{ts.text}</div>
            <button type="button" className="btn ghost sm icon" aria-label={t('close')} onClick={() => setToasts((x) => x.filter((y) => y.id !== ts.id))}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}
