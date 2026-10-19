import { beforeAll, describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n';
import Users from '../Users';
import { mockApi, renderPage, session } from '@/pages/__tests__/helpers';

const USERS = {
  items: [
    { id: 1, username: 'admin', display_name: 'Admin', email: '', role: 'admin', active: true, must_change_password: false, language: 'it', last_login_at: null, created_at: '2026-10-01T00:00:00+00:00', locked: false },
    { id: 2, username: 'mario', display_name: '', email: 'mario@example.com', role: 'viewer', active: true, must_change_password: false, language: 'it', last_login_at: null, created_at: '2026-10-01T00:00:00+00:00', locked: true },
  ],
};

describe('Users page', () => {
  beforeAll(() => i18n.changeLanguage('it'));

  it('validates the create form and shows backend password policy errors', async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      'GET /auth/me': session('admin', ['users.manage']),
      'GET /users': USERS,
      'POST /users': {
        status: 422,
        body: { error: { code: 'validation_failed', message: 'password does not satisfy the policy', params: { problems: ['too_common'], min_length: 12 } } },
      },
    });
    renderPage(<Users />);
    expect(await screen.findByText('mario')).toBeInTheDocument();
    // Locked users are flagged and the current user cannot be deleted.
    expect(screen.getByText('Bloccato')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Elimina admin' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: /Nuovo utente/ }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('Nome utente'), 'x');
    await user.type(within(dialog).getByLabelText('Password'), 'short');
    await user.type(within(dialog).getByLabelText('Ripeti la password'), 'different');
    await user.click(within(dialog).getByRole('button', { name: 'Salva' }));
    expect(within(dialog).getByText('Nome utente non valido.')).toBeInTheDocument();
    expect(within(dialog).getByText('La password deve avere almeno 12 caratteri.')).toBeInTheDocument();
    expect(within(dialog).getByText('Le due password non coincidono.')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST' && c.path === '/users')).toBe(false);

    await user.clear(within(dialog).getByLabelText('Nome utente'));
    await user.type(within(dialog).getByLabelText('Nome utente'), 'giulia');
    await user.clear(within(dialog).getByLabelText('Password'));
    await user.type(within(dialog).getByLabelText('Password'), 'Password1234');
    await user.clear(within(dialog).getByLabelText('Ripeti la password'));
    await user.type(within(dialog).getByLabelText('Ripeti la password'), 'Password1234');
    await user.click(within(dialog).getByRole('button', { name: 'Salva' }));
    expect(await within(dialog).findByText('La password è troppo comune.')).toBeInTheDocument();
    const post = calls.find((c) => c.method === 'POST' && c.path === '/users');
    expect(post?.body).toMatchObject({ username: 'giulia', role: 'viewer', must_change_password: true });
    expect(post?.headers['X-CSRF-Token']).toBe('csrf-test');
  });

  it('is denied without users.manage', async () => {
    mockApi({ 'GET /auth/me': session('viewer', ['cluster.read']) });
    renderPage(<Users />);
    expect(await screen.findByText('Il tuo ruolo non permette questa operazione.')).toBeInTheDocument();
  });
});
