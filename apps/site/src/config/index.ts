import { exemplo } from './sites/_exemplo';
import { assertValidAgenda } from '@/lib/agenda';
import type { SiteConfig } from '@/types/site';

/** Única lista a atualizar ao adicionar cliente; as rotas saem daqui no build. */
export const sites: SiteConfig[] = [exemplo];

/** Site mostrado na raiz `/`. */
export const defaultSite = exemplo;

export function getSite(slug: string): SiteConfig | undefined {
  return sites.find((site) => site.slug === slug);
}

/**
 * Fonte única das rotas dos quatro passos de `pages/[slug]/agendar/`: um `filter`
 * esquecido em um deles criaria o passo 2 de um cliente sem o passo 1.
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
