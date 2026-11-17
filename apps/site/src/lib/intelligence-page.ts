import { addDays } from './agenda';
import { summarize } from './clients';
import { loadFinance } from './finance-page';
import type { SiteConfig } from '@/types/site';
import type { IsoDate } from '@/types/agenda';

/** O que as telas de inteligência carregam: o financeiro, os clientes resumidos e a agenda da semana que vem. */
export async function loadIntelligence(url: URL, site: SiteConfig, today: IsoDate) {
  const finance = await loadFinance(url, site.slug, today);
  const { dados } = finance;
  const summaries = await Promise.all(
    (await dados.clients()).map(async (c) => summarize(c, await dados.clientAppointments(c.id), today, site.agenda)),
  );
  const nextWeek = await dados.appointmentsBetween(addDays(today, 1), addDays(today, 7));
  return { ...finance, summaries, nextWeek };
}
