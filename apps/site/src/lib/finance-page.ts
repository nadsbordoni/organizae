import { forTenant } from './dados-exemplo';
import { groupsOf, monthOptions, periodFor } from './finance';
import type { IsoDate } from '@/types/agenda';

/** O que toda tela financeira carrega: lançamentos, categorias e o mês escolhido em `?mes=`. */
export async function loadFinance(url: URL, tenantSlug: string, today: IsoDate) {
  const dados = forTenant(tenantSlug);
  const [entries, categories] = await Promise.all([dados.financialEntries(), dados.financialCategories()]);
  const months = monthOptions(today, 6);
  const period = periodFor(url.searchParams.get('mes'), today, months);
  return { dados, entries, categories, groups: groupsOf(categories), months, period };
}
