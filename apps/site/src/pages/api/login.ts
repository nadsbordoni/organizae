import type { APIRoute } from 'astro';
import { ApiError, api, apiEnabled } from '@/lib/api';
import { safeNext, startSession } from '@/lib/session';

/** Entrar no painel: troca e-mail e senha por um token da API e guarda o token no cookie da sessão. */
export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, redirect, url }) => {
  const form = await request.formData();
  const next = safeNext(form.get('next'));
  // Demonstração: sem API, qualquer e-mail entra, como antes.
  if (!apiEnabled()) return redirect(next, 303);

  try {
    const { access_token } = await api<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: { email: String(form.get('email') ?? '').trim(), password: String(form.get('password') ?? '') },
    });
    startSession(cookies, access_token, { remember: form.get('lembrar') === 'on', secure: url.protocol === 'https:' });
    return redirect(next, 303);
  } catch (error) {
    // 401 e 422 são e-mail ou senha errados; o resto é falha nossa, com outra mensagem.
    const reason = error instanceof ApiError && (error.status === 401 || error.status === 422) ? 'credenciais' : 'erro';
    const back = next === '/painel' ? '' : `&next=${encodeURIComponent(next)}`;
    return redirect(`/painel/login?erro=${reason}${back}`, 303);
  }
};
