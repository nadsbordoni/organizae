import type { AstroCookies } from 'astro';
import { ApiError, api, apiEnabled } from './api';
import { usuarioExemplo } from './dados-exemplo';
import type { AuthenticatedUser } from '@/types/painel';

/**
 * Sessão do painel: o token da API num cookie `httpOnly`, que o JavaScript da página não lê.
 * Sem API configurada, quem está logado é a Joana do exemplo.
 */

const COOKIE = 'organizae_sessao';

interface UserResponse {
  id: string;
  name: string;
  email: string;
  is_active: boolean;
  business_id: string | null;
}

/** Quando o token vence, em segundos desde 1970. Só lê o JWT: quem confere a assinatura é a API. */
function expiresAt(token: string): number | undefined {
  try {
    const part = (token.split('.')[1] ?? '').replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(part)) as { exp?: unknown };
    return typeof payload.exp === 'number' ? payload.exp : undefined;
  } catch {
    return undefined;
  }
}

/** `remember`: o cookie sobrevive ao fechar o navegador, até o token vencer. */
export function startSession(cookies: AstroCookies, token: string, { remember, secure }: { remember: boolean; secure: boolean }) {
  const exp = expiresAt(token);
  cookies.set(COOKIE, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure,
    path: '/',
    ...(remember && exp ? { maxAge: Math.max(0, exp - Math.floor(Date.now() / 1000)) } : {}),
  });
}

export function endSession(cookies: AstroCookies) {
  cookies.delete(COOKIE, { path: '/' });
}

export const sessionToken = (cookies: AstroCookies) => cookies.get(COOKIE)?.value;

/** Quem está logado, ou `undefined` sem sessão válida. Token vencido ou recusado apaga o cookie. */
export async function currentUser(cookies: AstroCookies): Promise<AuthenticatedUser | undefined> {
  if (!apiEnabled()) return usuarioExemplo;
  const token = sessionToken(cookies);
  if (!token) return undefined;
  try {
    const me = await api<UserResponse>('/users/me', { token });
    return {
      userId: me.id,
      // PROTÓTIPO: o painel ainda é montado com o negócio de exemplo; a fatia do negócio troca isto.
      tenantSlug: usuarioExemplo.tenantSlug,
      email: me.email,
      name: me.name,
      businessId: me.business_id,
      sessionId: 'api',
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      endSession(cookies);
      return undefined;
    }
    throw error;
  }
}

/** Para onde voltar depois do login: só caminhos do próprio painel, nunca outro site. */
export function safeNext(raw: unknown): string {
  const path = typeof raw === 'string' ? raw : '';
  const internal = path.startsWith('/painel') && !path.startsWith('//') && !path.includes('\\');
  return internal && !path.startsWith('/painel/login') ? path : '/painel';
}
