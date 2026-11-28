import type { AstroCookies } from 'astro';
import { ApiError, api } from './api';

/**
 * Cadastro do painel em dois passos: a conta (`POST /users` e login) e depois o negócio
 * (`POST /businesses`). O negócio é criado com o token da sessão, então a API liga o negócio
 * à conta logada; o front nunca escolhe a qual usuário ele pertence.
 */

/** O telefone é pedido no passo 1, mas a API o guarda no negócio (WhatsApp), criado no passo 2. */
const PHONE_COOKIE = 'organizae_cadastro_telefone';

export interface BusinessCategory {
  id: number;
  name: string;
}

export async function createAccount(data: { name: string; email: string; password: string }): Promise<string> {
  await api('/users', { method: 'POST', body: data });
  const { access_token } = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: { email: data.email, password: data.password },
  });
  return access_token;
}

export const businessCategories = () => api<BusinessCategory[]>('/business-categories');

export async function createBusiness(
  token: string,
  data: { name: string; categoryId: number; whatsapp: string; taxId: string; city: string },
): Promise<void> {
  await api('/businesses', {
    method: 'POST',
    token,
    body: {
      name: data.name,
      category_id: data.categoryId,
      whatsapp: data.whatsapp,
      tax_id: data.taxId,
      city: data.city,
      // A tela não pergunta; salões e barbearias atendem no local. Muda depois nas configurações.
      service_mode: 'PRESENCIAL',
    },
  });
}

export function rememberPhone(cookies: AstroCookies, phone: string, secure: boolean) {
  cookies.set(PHONE_COOKIE, phone, { httpOnly: true, sameSite: 'lax', secure, path: '/painel/cadastro', maxAge: 60 * 60 });
}

export const rememberedPhone = (cookies: AstroCookies) => cookies.get(PHONE_COOKIE)?.value ?? '';

export function forgetPhone(cookies: AstroCookies) {
  cookies.delete(PHONE_COOKIE, { path: '/painel/cadastro' });
}

/** Mensagem para a pessoa: o texto da API é técnico e em inglês. */
export function accountError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'Este e-mail já tem uma conta. Entre com ele ou use outro e-mail.';
    if (error.status === 422 && error.fields.includes('email')) return 'Confira o e-mail digitado.';
    if (error.status === 422 && error.fields.includes('password')) return 'A senha precisa ter de 8 a 128 caracteres.';
    if (error.status === 422) return 'Confira os dados digitados.';
  }
  return 'Não foi possível criar a conta agora. Tente de novo em instantes.';
}

export function businessError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422 && error.fields.includes('tax_id')) return 'CPF ou CNPJ inválido. Confira os números.';
    if (error.status === 422 && error.fields.includes('whatsapp')) return 'Confira o telefone com DDD.';
    if (error.status === 422) return 'Confira os dados do negócio.';
  }
  return 'Não foi possível criar o negócio agora. Tente de novo em instantes.';
}
