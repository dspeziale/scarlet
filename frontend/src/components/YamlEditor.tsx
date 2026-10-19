import { useEffect, useRef } from 'react';
import { EditorState } from '@codemirror/state';
import { EditorView, keymap } from '@codemirror/view';
import { basicSetup } from 'codemirror';
import { yaml as yamlLang } from '@codemirror/lang-yaml';
import { linter, lintGutter, type Diagnostic } from '@codemirror/lint';
import { MergeView } from '@codemirror/merge';
import { loadAll, YAMLException } from 'js-yaml';

/** Local YAML syntax check (structure is validated by the backend and by Kubernetes dry-run). */
export function yamlSyntaxErrors(text: string): { line: number; message: string }[] {
  try {
    loadAll(text);
    return [];
  } catch (e) {
    if (e instanceof YAMLException) return [{ line: (e.mark?.line ?? 0) + 1, message: e.reason || e.message }];
    return [{ line: 1, message: String(e) }];
  }
}

const yamlLinter = linter((view) => {
  const text = view.state.doc.toString();
  const out: Diagnostic[] = [];
  for (const err of yamlSyntaxErrors(text)) {
    const line = view.state.doc.line(Math.min(Math.max(err.line, 1), view.state.doc.lines));
    out.push({ from: line.from, to: line.to, severity: 'error', message: err.message });
  }
  return out;
});

const theme = EditorView.theme({
  '&': { backgroundColor: 'var(--surface)', color: 'var(--text)' },
  '.cm-gutters': { backgroundColor: 'var(--surface-2)', color: 'var(--text-3)', borderRight: '1px solid var(--border)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--primary) 7%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in srgb, var(--primary) 10%, transparent)' },
  '&.cm-focused': { outline: '2px solid var(--focus)' },
});

export function YamlEditor({
  value,
  onChange,
  readOnly,
  label,
  minHeight = 240,
}: {
  value: string;
  onChange?: (v: string) => void;
  readOnly?: boolean;
  label: string;
  minHeight?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          yamlLang(),
          theme,
          lintGutter(),
          yamlLinter,
          EditorState.readOnly.of(!!readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ 'aria-label': label }),
          EditorView.theme({ '.cm-content, .cm-gutter': { minHeight: `${minHeight}px` } }),
          keymap.of([]),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChangeRef.current?.(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, label]);

  // External value changes (e.g. reload) replace the document.
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div className="cm-host" ref={host} />;
}

/** Side-by-side diff (left: current, right: proposed). */
export function YamlDiff({ original, modified }: { original: string; modified: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const common = [basicSetup, yamlLang(), theme, EditorState.readOnly.of(true), EditorView.editable.of(false)];
    const mv = new MergeView({
      parent: host.current,
      a: { doc: original, extensions: common },
      b: { doc: modified, extensions: common },
      collapseUnchanged: { margin: 3, minSize: 6 },
      gutter: true,
    });
    return () => mv.destroy();
  }, [original, modified]);
  return <div className="cm-host" ref={host} style={{ maxHeight: 620, overflow: 'auto' }} />;
}
