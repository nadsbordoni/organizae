import { getSite } from '@/config';
import { formatDuration, nowInBusinessTime } from './agenda';
import { forTenant } from './dados-exemplo';
import { catalogTotal, compactPrice, endTime, serviceIds, serviceNames } from './painel';
import type { Agenda } from '@/types/agenda';
import type { AppointmentRow } from '@/types/painel';

/** O que toda tela da área da cliente carrega. `undefined`: negócio sem agenda, a página vira 404. */
export async function loadPortal(slug: string | undefined) {
  const site = getSite(slug ?? '');
  if (!site?.agenda) return undefined;
  const now = nowInBusinessTime(site.agenda.timezone);
  const { client, appointments } = await forTenant(site.slug).clientPortal();
  return { site, agenda: site.agenda, now, client, appointments, firstName: client.name.split(' ')[0]! };
}

/** Os textos de um atendimento que as telas repetem. */
export function describe(row: AppointmentRow, agenda: Agenda) {
  const price = catalogTotal([row], agenda);
  return {
    service: serviceNames(row, agenda),
    end: endTime(row),
    duration: formatDuration(row.duration_min),
    price: price ? compactPrice(price) : undefined,
    /** Para o reagendar e o "Agendar de novo" abrirem com o mesmo serviço. */
    query: `servicos=${(serviceIds(row) ?? []).join(',')}`,
  };
}
