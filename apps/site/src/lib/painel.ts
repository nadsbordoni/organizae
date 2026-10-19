import { formatPrice, parsePrice, toClock, toMinutes } from './agenda';
import type { AppointmentStatus } from './dashboard-status';
import type { IconName } from '@/types/blocks';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow } from '@/types/painel';

/** Cor de estado do painel. Cada uma vira `--site-panel-<tom>` no tema. */
export type PanelTone = 'info' | 'positive' | 'attention' | 'danger';

/** Como cada situação aparece no selo. */
export const STATUS_BADGE: Record<AppointmentStatus, { label: string; tone: PanelTone; icon: IconName }> = {
  pending: { label: 'A confirmar', tone: 'attention', icon: 'clock' },
  confirmed: { label: 'Confirmado', tone: 'info', icon: 'check-circle' },
  done: { label: 'Atendido', tone: 'positive', icon: 'check' },
  cancelled: { label: 'Cancelado', tone: 'danger', icon: 'close' },
};

/** 'Bom dia', 'Boa tarde' ou 'Boa noite', pela hora de parede do negócio. */
export function greeting(minutes: number): string {
  const hour = Math.floor(minutes / 60);
  if (hour >= 5 && hour < 12) return 'Bom dia';
  if (hour >= 12 && hour < 18) return 'Boa tarde';
  return 'Boa noite';
}

/** Primeiro nome, ou nada. E-mail digitado no lugar do nome não vira saudação. */
export function firstName(name: string | undefined): string | undefined {
  const first = name?.trim().split(/\s+/)[0];
  return first && !first.includes('@') ? first : undefined;
}

/** 'Marina Costa' → 'MC'; 'Bia' → 'BI'. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return `${words[0]![0]}${words[words.length - 1]![0]}`.toUpperCase();
  return (words[0] ?? '?').slice(0, 2).toUpperCase();
}

/** Tom estável por nome: a mesma cliente tem sempre a mesma cor de iniciais. */
export function toneFor(name: string): PanelTone {
  const tones: PanelTone[] = ['positive', 'info', 'attention'];
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return tones[hash % tones.length]!;
}

/*
 * Datas por extenso. `timeZone: 'UTC'` porque a data já vem na hora de parede
 * do negócio: converter de novo deslocaria o dia.
 */
const at = (date: IsoDate) => new Date(`${date}T12:00:00Z`);
const capitalize = (text: string) => `${text.charAt(0).toUpperCase()}${text.slice(1)}`;

/** 'Segunda-feira, 28 de setembro'. */
export function weekdayLabel(date: IsoDate): string {
  return capitalize(
    new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(at(date)),
  );
}

/** 'setembro de 2026'. */
export function monthLabel(date: IsoDate): string {
  return new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(at(date));
}

/** '28 set.' */
export function shortDayLabel(date: IsoDate): string {
  return new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(at(date));
}

/** Fim de um atendimento. */
export function endTime(row: Pick<AppointmentRow, 'start_time' | 'duration_min'>): string {
  return toClock(toMinutes(row.start_time) + row.duration_min);
}

function serviceIds(row: AppointmentRow): string[] | undefined {
  try {
    const ids = JSON.parse(row.service_ids) as unknown;
    return Array.isArray(ids) ? ids.map(String) : undefined;
  } catch {
    return undefined;
  }
}

/** Nomes dos serviços. Id órfão (serviço tirado do catálogo) aparece como id: melhor que sumir. */
export function serviceNames(row: AppointmentRow, agenda: Agenda | undefined): string {
  const ids = serviceIds(row);
  if (!ids) return 'Serviço não identificado';
  const names = new Map(
    (agenda?.categories ?? []).flatMap((category) =>
      category.services.map((service) => [service.id, service.name] as const),
    ),
  );
  return ids.map((id) => names.get(id) ?? id).join(' + ');
}

/**
 * Soma dos preços do catálogo nos atendimentos dados. `undefined` se algum
 * serviço não tem preço legível: total errado que parece completo é pior que
 * nenhum total.
 */
export function catalogTotal(rows: AppointmentRow[], agenda: Agenda | undefined): string | undefined {
  const prices = new Map(
    (agenda?.categories ?? []).flatMap((category) =>
      category.services.map((service) => [service.id, service.price] as const),
    ),
  );

  let cents = 0;
  for (const row of rows) {
    const ids = serviceIds(row);
    if (!ids) return undefined;
    for (const id of ids) {
      const value = parsePrice(prices.get(id));
      if (value === undefined) return undefined;
      cents += value;
    }
  }
  return formatPrice(cents);
}

/** 'R$ 8.460,00' → 'R$ 8.460': no resumo os centavos redondos só ocupam espaço. */
export function compactPrice(text: string): string {
  return text.replace(/,00$/, '');
}
