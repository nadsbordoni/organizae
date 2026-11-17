import { ORGANIZAE_API_URL } from 'astro:env/server';

/**
 * Cliente da API (`apps/api`), só no servidor: o navegador nunca fala com a API nem vê o token.
 * Sem `ORGANIZAE_API_URL`, o painel continua com os dados de exemplo.
 */

const base = () => ORGANIZAE_API_URL?.replace(/\/+$/, '');

export const apiEnabled = () => Boolean(base());

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

interface Options {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  token?: string;
  body?: unknown;
}

export async function api<T>(path: string, { method = 'GET', token, body }: Options = {}): Promise<T> {
  const root = base();
  if (!root) throw new Error('ORGANIZAE_API_URL não está configurada.');

  const response = await fetch(`${root}/api/v1${path}`, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    // A página espera a API; sem limite, uma API travada prenderia a página para sempre.
    signal: AbortSignal.timeout(10_000),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* resposta sem JSON: fica o texto do status */
    }
    throw new ApiError(response.status, detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}
