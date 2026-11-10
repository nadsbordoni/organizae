import { weeklySummary } from './agenda';
import type { Block } from '@/types/blocks';
import type { SiteConfig } from '@/types/site';

/**
 * PALAVRA RESERVADA: nenhuma coleção pode usar este slug, senão as rotas colidem em
 * `/{slug}/agendar`. A checagem está em `pages/[slug]/[collection].astro`.
 */
export const BOOKING_PATH = 'agendar';

/**
 * Preenche os blocos que DERIVAM da configuração do site, para os componentes receberem só `block`.
 * Horário escrito à mão ao lado da agenda vira, cedo ou tarde, dois horários na mesma página.
 */
export function resolveBlocks(site: SiteConfig): Block[] {
  return site.blocks.map((block) => {
    if (block.type === 'booking') {
      if (!site.agenda && !block.href) {
        throw new Error(
          `Site "${site.slug}": bloco \`booking\` sem \`agenda\` configurada. ` +
            'Defina `agenda` em `SiteConfig`, ou aponte `href` para o agendamento externo.',
        );
      }
      return { ...block, href: block.href ?? `/${site.slug}/${BOOKING_PATH}` };
    }

    if (block.type === 'hours' && !block.schedule) {
      if (!site.agenda) {
        throw new Error(
          `Site "${site.slug}": bloco \`hours\` sem \`schedule\` e sem \`agenda\`. ` +
            'Um dos dois precisa dizer qual é o expediente.',
        );
      }
      return { ...block, schedule: weeklySummary(site.agenda) };
    }

    return block;
  });
}
