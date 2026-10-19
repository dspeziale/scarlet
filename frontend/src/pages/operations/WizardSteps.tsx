import { Check } from 'lucide-react';

/** Vertical step list: completed steps are clickable, future steps are not. */
export function WizardSteps({
  steps,
  current,
  maxReached,
  onSelect,
  label,
}: {
  steps: string[];
  current: number;
  maxReached: number;
  onSelect: (i: number) => void;
  label: string;
}) {
  return (
    <nav aria-label={label}>
      <ol className="wizard-steps">
        {steps.map((s, i) => {
          const done = i < current || (i <= maxReached && i !== current);
          const cls = i === current ? 'current' : done ? 'done' : '';
          const clickable = i !== current && i <= maxReached;
          const content = (
            <>
              <span className="num" aria-hidden="true">
                {done && i !== current ? <Check size={13} /> : i + 1}
              </span>
              <span className="txt">{s}</span>
            </>
          );
          return (
            <li key={s} className={cls} aria-current={i === current ? 'step' : undefined}>
              {clickable ? (
                <button type="button" onClick={() => onSelect(i)}>
                  {content}
                </button>
              ) : (
                content
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
