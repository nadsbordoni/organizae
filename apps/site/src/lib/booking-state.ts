import { hasSlots, isIsoDate, slotsFor, totalDuration } from './agenda';
import type { Agenda, ClockTime, IsoDate, Service } from '@/types/agenda';

/**
 * O estado do agendamento mora na URL.
 *
 * Cada passo é uma página de verdade (`/agendar`, `/agendar/data`,
 * `/agendar/revisao`, `/agendar/enviado`) e o que já foi escolhido viaja na
 * query: `?servicos=blindagem,design&data=2026-09-15&hora=14:00`.
 *
 * POR QUE NA URL, e não em memória ou `sessionStorage`:
 *   - o botão voltar do navegador funciona sozinho, sem `pushState` nenhum;
 *   - recarregar a página não perde a escolha;
 *   - dá para mandar o link de um horário para alguém;
 *   - o estado é inspecionável, o que torna um bug reproduzível.
 *
 * O preço é que a URL é EDITÁVEL: qualquer coisa pode chegar aqui. Por isso
 * nada é confiado — `readSelection()` valida tudo contra o catálogo e contra o
 * motor de disponibilidade, e devolve só o que sobrevive.
 *
 * A observação escrita pela cliente NÃO entra na URL: é texto pessoal, ficaria
 * na barra de endereço e no histórico do navegador. Ela viaja em
 * `sessionStorage`, que morre quando a aba fecha.
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

/** Minutos do atendimento inteiro — é o que o motor usa para achar vaga. */
export function selectionMinutes(selection: Selection): number {
  return totalDuration(selection.services);
}

/**
 * Lê a escolha da query, descartando o que não faz mais sentido.
 *
 * Um serviço que saiu do catálogo, uma data que já passou, um horário que
 * deixou de caber depois que outro serviço entrou — tudo isso some aqui, em vez
 * de virar um agendamento impossível três telas adiante.
 */
export function readSelection(
  agenda: Agenda,
  search: string,
  now: { date: IsoDate; minutes: number },
  /**
   * Falso só na conclusão: o pedido já saiu, e o horário pode ter deixado de ser
   * oferecido no caminho (a antecedência mínima vence enquanto o WhatsApp abre).
   * Revalidar ali devolvia a cliente ao início sem o resumo.
   */
  { checkAvailability = true }: { checkAvailability?: boolean } = {},
): Selection {
  const params = new URLSearchParams(search);
  const catalog = agenda.categories.flatMap((category) => category.services);

  const wanted = new Set((params.get(PARAM.services) ?? '').split(',').filter(Boolean));
  // A ordem é a do catálogo, não a da URL: assim a lista de revisão sai sempre
  // igual, independentemente da ordem em que as caixas foram marcadas.
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

  // O horário precisa estar entre os OFERECIDOS, não só ter formato válido: é o
  // que impede marcar em cima do almoço editando a barra de endereço.
  const valid = checkAvailability
    ? slotsFor({ agenda, service, date, now }).includes(time)
    : /^([01]\d|2[0-3]):[0-5]\d$/.test(time);
  if (valid) selection.time = time;

  return selection;
}

/** Monta o endereço de um passo carregando a escolha atual. */
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
    // Safari em navegação privada antiga lança ao tocar em sessionStorage. A
    // observação é opcional; perder ela não pode derrubar o fluxo.
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
