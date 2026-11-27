/// <reference types="astro/client" />

declare namespace App {
  interface Locals {
    /** Quem está logado no painel, posto pelo `middleware.ts`. */
    user: import('@/types/painel').AuthenticatedUser;
    /** Token da API, para as páginas chamarem as rotas protegidas. Vazio na demonstração. */
    token?: string;
  }
}
