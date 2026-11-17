import { hasSlots, isIsoDate, slotsFor, totalDuration } from './agenda';
import type { Agenda, ClockTime, IsoDate, Service } from '@/types/agenda';

/**
 * Estado do agendamento na URL (`?servicos=a,b&data=2026-09-15&hora=14:00`), para voltar, recarregar
 * e compartilhar funcionarem. A URL é EDITÁVEL: `readSelection()` valida tudo. A observação da
 * cliente NÃO vai na URL (ficaria no histórico): vai em `sessionStorage`.
 */

const PARAM = {
  services: 'servicos',
  date: 'data',
  time: 'hora',
} as const;

const NOTES_KEY = 'bio-agenda:observacoes';

export interface Selection {
  services: Service[];
  date?: IsoDate;
  time?: ClockTime;
}

export function selectionMinutes(selection: Selection): number {
  return totalDuration(selection.services);
}

/** Descarta o que não vale mais: serviço fora do catálogo, data passada, horário que deixou de caber. */
export function readSelection(
  agenda: Agenda,
  search: string,
  now: { date: IsoDate; minutes: number },
  /** Falso só na conclusão: o pedido já saiu e o horário pode ter vencido a antecedência no caminho. */
  { checkAvailability = true }: { checkAvailability?: boolean } = {},
): Selection {
  const params = new URLSearchParams(search);
  const catalog = agenda.categories.flatMap((category) => category.services);

  const wanted = new Set((params.get(PARAM.services) ?? '').split(',').filter(Boolean));
  // Ordem do catálogo, não da URL: a revisão sai igual em qualquer ordem de marcação.
  const services = catalog.filter(
    (service) => wanted.has(service.id) && !service.hidden && !service.soon,
  );

  const selection: Selection = { services };
  if (!services.length) return selection;

  const service = { durationMinutes: totalDuration(services) };

  const date = params.get(PARAM.date) ?? undefined;
  if (!date || !isIsoDate(date)) return selection;
  if (checkAvailability && !hasSlots({ agenda, service, date, now })) return selection;
  selection.date = date;

  const time = params.get(PARAM.time) ?? undefined;
  if (!time) return selection;

  // Precisa estar entre os OFERECIDOS, não só ter formato válido: impede marcar em cima do almoço pela URL.
  const valid = checkAvailability
    ? slotsFor({ agenda, service, date, now }).includes(time)
    : /^([01]\d|2[0-3]):[0-5]\d$/.test(time);
  if (valid) selection.time = time;

  return selection;
}

export function stepHref(base: string, step: '' | 'data' | 'revisao' | 'enviado', selection: Selection): string {
  const params = new URLSearchParams();

  if (selection.services.length) {
    params.set(PARAM.services, selection.services.map((service) => service.id).join(','));
  }
  if (selection.date) params.set(PARAM.date, selection.date);
  if (selection.time) params.set(PARAM.time, selection.time);

  const path = step ? `${base}/${step}` : base;
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function readNotes(): string {
  try {
    return sessionStorage.getItem(NOTES_KEY) ?? '';
  } catch {
    // Safari antigo em navegação privada lança aqui; a observação é opcional e NÃO pode derrubar o fluxo.
    return '';
  }
}

export function writeNotes(value: string): void {
  try {
    if (value) sessionStorage.setItem(NOTES_KEY, value);
    else sessionStorage.removeItem(NOTES_KEY);
  } catch {
    /* mesmo motivo de `readNotes` */
  }
}
