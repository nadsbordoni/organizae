import { defineMiddleware } from 'astro:middleware';
import { usuarioExemplo } from '@/lib/dados-exemplo';
import { currentUser, sessionToken } from '@/lib/session';

/**
 * Guarda do painel. Com a API, sem sessão válida a pessoa volta para o login, que devolve para onde
 * ela estava. As telas de entrar, criar conta e recuperar senha ficam abertas.
 */
const OPEN = ['/painel/login', '/painel/cadastro', '/painel/senha'];

export const onRequest = defineMiddleware(async (context, next) => {
  const { pathname, search } = context.url;
  const panel = pathname === '/painel' || pathname.startsWith('/painel/');
  if (context.isPrerendered || !panel) return next();

  const open = OPEN.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  const user = await currentUser(context.cookies);
  if (user) {
    // Conta sem negócio (cadastro pela metade): o painel não tem o que mostrar até terminar.
    if (user.businessId === null && !open) return context.redirect('/painel/cadastro/empresa', 303);
    context.locals.user = user;
    context.locals.token = sessionToken(context.cookies);
    return next();
  }
  // A tela aberta continua acessível sem sessão; o usuário de exemplo só preenche o que ela não usa.
  if (open) {
    context.locals.user = usuarioExemplo;
    return next();
  }
  return context.redirect(`/painel/login?next=${encodeURIComponent(pathname + search)}`, 303);
});
