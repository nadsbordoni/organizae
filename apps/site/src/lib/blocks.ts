import { weeklySummary } from './agenda';
import type { Block } from '@/types/blocks';
import type { SiteConfig } from '@/types/site';

/**
 * Caminho do fluxo de agendamento de um site.
 *
 * ⚠️ PALAVRA RESERVADA: nenhuma coleção pode usar este slug, senão as duas rotas
 * colidiriam em `/{slug}/agendar`. A checagem está em `pages/[slug]/[collection].astro`.
 */
export const BOOKING_PATH = 'agendar';

/**
 * Preenche os blocos que DERIVAM da configuração do site, antes de renderizar.
 *
 * Existe para que os componentes de bloco continuem recebendo só `block`: o
 * registry de `BlockList.astro` fica uniforme, e tudo que um bloco precisa saber
 * do site inteiro é resolvido aqui, num lugar só.
 *
 * É o mesmo princípio de `lib/links.ts` — quem edita a configuração escreve o
 * mínimo, e o que dá para deduzir é deduzido. Um horário escrito à mão ao lado
 * de uma agenda estruturada vira, mais cedo ou mais tarde, dois horários
 * diferentes na mesma página.
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
