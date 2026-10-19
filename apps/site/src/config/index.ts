import { exemplo } from './sites/_exemplo';
import { assertValidAgenda } from '@/lib/agenda';
import type { SiteConfig } from '@/types/site';

/**
 * Registro de sites — a única lista a atualizar ao adicionar cliente. As rotas
 * `/{slug}` e `/{slug}/{coleção}` são geradas daqui no build.
 */
export const sites: SiteConfig[] = [exemplo];

/** Site mostrado na raiz `/`. */
export const defaultSite = exemplo;

export function getSite(slug: string): SiteConfig | undefined {
  return sites.find((site) => site.slug === slug);
}

/**
 * Rotas dos passos do agendamento — usada pelos quatro arquivos de
 * `pages/[slug]/agendar/`.
 *
 * Existe para que os quatro gerem exatamente o mesmo conjunto de páginas: um
 * `filter` esquecido em um deles criaria o passo 2 de um cliente que não tem o
 * passo 1.
 */
export function bookingPaths() {
  return sites
    .filter((site) => site.agenda)
    .map((site) => {
      assertValidAgenda(site.agenda!, site.slug);
      return {
        params: { slug: site.slug },
        props: { site, agenda: site.agenda! },
      };
    });
}
