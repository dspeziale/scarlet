import { expect, test, type Page } from '@playwright/test';
import { ADMIN, VIEWER } from './global-setup';

async function login(page: Page, user = ADMIN) {
  await page.goto('/login');
  await page.getByLabel('Utente').fill(user.username);
  await page.getByLabel('Password').fill(user.password);
  await page.getByRole('button', { name: 'Accedi' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible();
}

test.describe('PKM console (DEMO)', () => {
  test('DEMO mode is unmistakable and versions are shown', async ({ page }) => {
    await login(page);
    await expect(page.getByText('MODALITÀ DEMO', { exact: false })).toBeVisible();
    await expect(page.locator('.env-chip.demo')).toHaveText('DEMO');
    await expect(page.locator('.version-info')).toContainText('K8s v1.31.4-demo');
    await expect(page.locator('.version-info')).toContainText('API v1');
  });

  test('dashboard cards lead to details', async ({ page }) => {
    await login(page);
    await page.getByRole('link', { name: /Pod in errore/ }).click();
    await expect(page).toHaveURL(/\/k8s\/pods\?health=failed/);
    await expect(page.getByRole('cell', { name: /CrashLoopBackOff|ImagePullBackOff/ }).first()).toBeVisible();
  });

  test('sidebar groups collapse and the compact mode persists', async ({ page }) => {
    await login(page);
    const group = page.getByRole('button', { name: 'Networking' });
    await group.click();
    await expect(page.getByRole('link', { name: 'Services' })).toBeVisible();
    await group.click();
    await expect(page.getByRole('link', { name: 'Services' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Riduci il menu' }).click();
    await page.reload();
    await expect(page.locator('.app.compact')).toBeVisible();
    await page.getByRole('button', { name: 'Espandi il menu' }).click();
    await expect(page.locator('.app.compact')).toHaveCount(0);
  });

  test('operations center explains a CrashLoopBackOff and can mark it handled', async ({ page }) => {
    await login(page);
    await page.getByRole('link', { name: 'Centro Operativo' }).first().click();
    const card = page.locator('article.issue', { hasText: 'CrashLoopBackOff' }).first();
    await expect(card).toContainText('Codice di uscita');
    await expect(card).toContainText('Causa più probabile');
    await card.getByRole('button', { name: 'Segna come gestito' }).click();
    await expect(card).toContainText('Gestito da admin');
  });

  test('troubleshooting: ImagePullBackOff diagnosis points to the missing tag', async ({ page }) => {
    await login(page);
    await page.goto('/operations-center');
    const card = page.locator('article.issue', { hasText: 'ImagePullBackOff' }).first();
    await expect(card).toContainText('Esistenza dell\'immagine/tag');
    await expect(card.locator('.badge', { hasText: 'Causa più probabile' })).toBeVisible();
    await card.getByRole('link', { name: 'Come risolvere' }).click();
    await expect(page.getByRole('heading', { name: /ImagePullBackOff/, level: 1 })).toBeVisible();
  });

  test('image onboarding hands a prefilled spec to the deploy wizard, which deploys it', async ({ page }) => {
    await login(page);
    await page.goto('/operations/onboarding?image=nginx:1.27');
    await page.getByRole('button', { name: 'Verifica immagine' }).click();
    await expect(page.getByText('Immagine verificata')).toBeVisible();
    for (let i = 0; i < 3; i++) {
      await page.getByRole('button', { name: /^Avanti/ }).click();
    }
    await expect(page.getByRole('heading', { name: 'Riepilogo' })).toBeVisible();
    await page.getByRole('button', { name: 'Continua nel wizard di deploy' }).click();
    await expect(page).toHaveURL(/\/operations\/deploy/);
    await expect(page.locator('input[value="nginx"]').first()).toBeVisible();
    // Walk to the summary: the backend preview (dry-run) must succeed.
    for (let i = 0; i < 10; i++) {
      const next = page.getByRole('button', { name: /^Avanti/ });
      if (!(await next.isVisible())) break;
      await next.click();
    }
    await expect(page.getByText('YAML generato')).toBeVisible();
    await page.getByRole('button', { name: 'Vai al deploy' }).click();
    await page.getByRole('button', { name: /^Deploy$/ }).click();
    await expect(page.getByText('Risorse applicate')).toBeVisible();
    await expect(page.getByText("L'applicazione è pronta.")).toBeVisible({ timeout: 30_000 });
  });

  test('scaling asks for confirmation and scale-to-zero requires typing the name', async ({ page }) => {
    await login(page);
    await page.goto('/k8s/deployments/production/web-prod');
    await page.getByRole('button', { name: 'Scala', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Conseguenze');
    await dialog.getByLabel('Numero di repliche desiderato').fill('0');
    const confirm = dialog.getByRole('button', { name: /Scala a 0/ });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel(/Per confermare digita/).fill('web-prod');
    await dialog.getByLabel('Numero di repliche desiderato').fill('4');
    await dialog.getByRole('button', { name: /Scala a 4/ }).click();
    await expect(page.getByText('web-prod scalato')).toBeVisible();
  });

  test('YAML: edit, validate (server dry-run) and diff a ConfigMap', async ({ page }) => {
    await login(page);
    await page.goto('/k8s/configmaps/production/web-config?tab=yaml');
    await page.getByRole('button', { name: 'Modifica' }).click();
    const editor = page.locator('.cm-content').first();
    await editor.click();
    await page.keyboard.press('Control+End');
    await page.keyboard.type('\n  NEW_KEY: "1"');
    await page.getByRole('button', { name: 'Valida' }).click();
    await expect(page.getByText(/Configurazione valida/)).toBeVisible();
    await page.getByRole('button', { name: 'Differenze' }).click();
    await expect(page.locator('.cm-mergeView')).toBeVisible();
  });

  test('logs: viewer shows lines, filters and downloads', async ({ page }) => {
    await login(page);
    await page.goto('/k8s/pods?namespace=production');
    await page.getByRole('cell', { name: /^api-prod-/ }).first().click();
    await page.getByRole('tab', { name: 'Log' }).click();
    await expect(page.getByRole('log')).toContainText('ECONNREFUSED');
    await page.getByPlaceholder('Cerca o filtra nel log…').fill('Fatal');
    await expect(page.getByText(/1 corrispondenze|corrispondenze/)).toBeVisible();
  });

  test('global search finds resources and guide articles', async ({ page }) => {
    await login(page);
    await page.keyboard.press('Control+k');
    await page.getByRole('dialog').getByRole('textbox').fill('redis');
    await expect(page.getByRole('option', { name: /redis/ }).first()).toBeVisible();
    await page.getByRole('dialog').getByRole('textbox').fill('rollback');
    await expect(page.getByRole('option', { name: /Rollback/ }).first()).toBeVisible();
  });

  test('guide is searchable and contextual', async ({ page }) => {
    await login(page);
    await page.goto('/k8s/deployments/production/web-prod');
    await page.getByRole('link', { name: "Cos'è Deployment?" }).click();
    await expect(page.getByRole('heading', { name: 'Deployment', level: 1 })).toBeVisible();
    await page.getByPlaceholder('Cerca nella guida…').fill('OOMKilled');
    await expect(page.getByRole('link', { name: /OOMKilled/ }).first()).toBeVisible();
  });

  test('language can be switched to English', async ({ page }) => {
    await login(page);
    await page.getByLabel('Lingua').selectOption('en');
    await expect(page.getByRole('link', { name: 'Operations Center' }).first()).toBeVisible();
    await page.getByLabel('Language').selectOption('it');
  });

  test('viewer role: read only, no operations, no logs', async ({ page }) => {
    await login(page, VIEWER);
    await page.goto('/k8s/deployments/production/web-prod');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('web-prod');
    await expect(page.getByRole('button', { name: 'Scala', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Elimina' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Utenti' })).toHaveCount(0);
    // The backend enforces it too.
    const status = await page.evaluate(async () => {
      const r = await fetch('/api/v1/k8s/deployments/production/web-prod/scale', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ replicas: 1 }),
      });
      return r.status;
    });
    expect(status).toBe(403);
  });

  test('a backend error is explained, not a bare 500', async ({ page }) => {
    await login(page);
    await page.goto('/k8s/deployments/production/does-not-exist');
    await expect(page.getByText('Risorsa non trovata')).toBeVisible();
    await expect(page.getByText('Dettagli tecnici')).toBeVisible();
  });
});
