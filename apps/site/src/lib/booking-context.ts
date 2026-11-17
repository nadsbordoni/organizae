import { BOOKING_PATH } from './blocks';
import type { BookingContext } from './booking-ui';
import type { SiteConfig } from '@/types/site';

/** O que os passos com calendário precisam no navegador. `base` é a página do passo de data e horário. */
export function bookingContext(site: SiteConfig, base = `/${site.slug}/${BOOKING_PATH}`): BookingContext {
  const agenda = site.agenda!;
  return {
    // Serviço escondido fica de fora: `readSelection()` valida a URL contra ESTE catálogo.
    agenda: {
      ...agenda,
      categories: agenda.categories
        .filter((category) => !category.hidden)
        .map((category) => ({
          ...category,
          services: category.services.filter((service) => !service.hidden),
        })),
    },
    business: {
      name: site.profile.name,
      base,
      homeHref: `/${site.slug}`,
      // Para o arquivo de calendário; vem do bloco de localização, sem redigitar.
      address: site.blocks.find((block) => block.type === 'location')?.address.join(', '),
    },
  };
}

/** JSON que as páginas com calendário embutem: páginas separadas não dividem memória. */
export function readContext(): BookingContext | undefined {
  const raw = document.getElementById('dados-agendamento')?.textContent;
  if (!raw) return undefined;

  return JSON.parse(raw) as BookingContext;
}
