import type { APIRoute } from 'astro';
import { endSession } from '@/lib/session';

/** Sair do painel: apaga o cookie da sessão. O token vence sozinho na API. */
export const prerender = false;

export const POST: APIRoute = ({ cookies, redirect }) => {
  endSession(cookies);
  return redirect('/painel/login', 303);
};
