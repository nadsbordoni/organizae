import { WEEKDAYS, addDays, formatPrice, freeWindows, parsePrice, scheduleFor, toClock, toMinutes, weekdayOf } from './agenda';
import type { AppointmentStatus } from './dashboard-status';
import type { IconName } from '@/types/blocks';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow } from '@/types/painel';

/** Cada tom vira `--site-panel-<tom>` no tema. */
export type PanelTone = 'info' | 'positive' | 'attention' | 'danger';

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

/** `undefined` se vazio, ou se for e-mail digitado no lugar do nome. */
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

/** Hash do nome: a mesma cliente tem sempre a mesma cor de iniciais. */
export function toneFor(name: string): 'pink-soft' | 'yellow-soft' | 'blue-soft' | 'green' {
  const tones = ['pink-soft', 'yellow-soft', 'blue-soft', 'green'] as const;
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return tones[hash % tones.length]!;
}

// `timeZone: 'UTC'`: a data já vem na hora de parede do negócio, e converter de novo deslocaria o dia.
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

/** '18 de junho de 2025'. */
export function longDateLabel(date: IsoDate): string {
  return new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(at(date));
}

/** '04 jun'. */
export function dayMonthLabel(date: IsoDate): string {
  const month = new Intl.DateTimeFormat('pt-BR', { month: 'short', timeZone: 'UTC' }).format(at(date));
  return `${date.slice(8, 10)} ${month.replace('.', '')}`;
}

/** '12 de agosto', sem o ano. */
export function birthdayLabel(date: IsoDate): string {
  return new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long', timeZone: 'UTC' }).format(at(date));
}

/** '28 set.' */
export function shortDayLabel(date: IsoDate): string {
  return new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(at(date));
}

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

/** Id órfão (serviço tirado do catálogo) aparece como id, em vez de sumir. */
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

/** Em centavos. `undefined` se algum serviço não tem preço legível: total errado que parece completo é pior que nenhum. */
export function catalogCents(rows: AppointmentRow[], agenda: Agenda | undefined): number | undefined {
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
  return cents;
}

export function catalogTotal(rows: AppointmentRow[], agenda: Agenda | undefined): string | undefined {
  const cents = catalogCents(rows, agenda);
  return cents === undefined ? undefined : formatPrice(cents);
}

/** 'R$ 8.460,00' → 'R$ 8.460': no resumo os centavos redondos só ocupam espaço. */
export function compactPrice(text: string): string {
  return text.replace(/,00$/, '');
}

/** De domingo a sábado. */
export function weekOf(date: IsoDate): IsoDate[] {
  const sunday = addDays(date, -WEEKDAYS.indexOf(weekdayOf(date)));
  return WEEKDAYS.map((_, offset) => addDays(sunday, offset));
}

/** '8 – 14 nov' ou '29 nov – 5 dez'. */
export function weekRangeLabel(first: IsoDate, last: IsoDate): string {
  const month = (date: IsoDate) =>
    new Intl.DateTimeFormat('pt-BR', { month: 'short', timeZone: 'UTC' }).format(at(date)).replace('.', '');
  const day = (date: IsoDate) => Number(date.slice(8, 10));
  return month(first) === month(last)
    ? `${day(first)} – ${day(last)} ${month(last)}`
    : `${day(first)} ${month(first)} – ${day(last)} ${month(last)}`;
}

/** '20/06/2025', ou '20/06' sem o ano. */
export function numericDate(date: IsoDate, withYear = true): string {
  const [year, month, day] = date.split('-');
  return withYear ? `${day}/${month}/${year}` : `${day}/${month}`;
}

/** '9 — 14 de novembro de 2026', ou '30 de novembro — 5 de dezembro de 2026'. */
export function weekRangeLongLabel(first: IsoDate, last: IsoDate): string {
  const parts = (date: IsoDate) =>
    new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
      .formatToParts(at(date))
      .reduce<Record<string, string>>((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  const a = parts(first);
  const b = parts(last);
  return a.month === b.month
    ? `${a.day} — ${b.day} de ${b.month} de ${b.year}`
    : `${a.day} de ${a.month} — ${b.day} de ${b.month} de ${b.year}`;
}

/** 'Seg', 'Ter'… */
export function shortWeekday(date: IsoDate): string {
  const name = new Intl.DateTimeFormat('pt-BR', { weekday: 'short', timeZone: 'UTC' }).format(at(date));
  return capitalize(name.replace('.', ''));
}

/** Fração do expediente ocupada, de 0 a 1. `undefined` com o dia fechado: fechado NÃO é vazio. */
export function dayLoad(
  agenda: Agenda | undefined,
  date: IsoDate,
  rows: Array<Pick<AppointmentRow, 'start_time' | 'duration_min'>>,
): number | undefined {
  const hours = agenda ? scheduleFor(agenda, date).hours : null;
  if (!hours) return undefined;

  const minutes = (windows: Array<[number, number]>) =>
    windows.reduce((sum, [start, end]) => sum + (end - start), 0);
  const open = minutes(freeWindows(hours));
  if (!open) return undefined;

  const busy = rows.map((row) => ({ from: row.start_time, to: endTime(row) }));
  return (open - minutes(freeWindows(hours, busy))) / open;
}

/** Resposta para conta ligada a um negócio que saiu de `config/sites/` sem mexer no banco. */
export function tenantNotConfigured(tenantSlug: string): Response {
  return new Response(`Conta ligada ao negócio "${tenantSlug}", que não está configurado.`, {
    status: 500,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

/** Os últimos `count` meses até o de `today`, do mais antigo ao atual: `{ short: 'Dez', long: 'dezembro' }`. */
export function lastMonths(today: IsoDate, count: number): Array<{ short: string; long: string }> {
  const [year, month] = today.split('-').map(Number) as [number, number];
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(Date.UTC(year, month - 1 - (count - 1 - i), 1));
    const short = new Intl.DateTimeFormat('pt-BR', { month: 'short', timeZone: 'UTC' }).format(date);
    const long = new Intl.DateTimeFormat('pt-BR', { month: 'long', timeZone: 'UTC' }).format(date);
    return { short: capitalize(short.replace('.', '')), long };
  });
}

/** '5511987650101' → '(11) 98765-0101'. Fora desse formato, devolve como veio. */
export function formatPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '');
  const local = digits.startsWith('55') ? digits.slice(2) : digits;
  return /^\d{10,11}$/.test(local) ? `(${local.slice(0, 2)}) ${local.slice(2, -4)}-${local.slice(-4)}` : phone;
}

/** Segmentos de negócio do cadastro e da configuração inicial. Devem vir das categorias de negócio do back quando houver rota. */
export const BUSINESS_SEGMENTS = ['Beleza e bem-estar', 'Cabelo', 'Unhas', 'Estética', 'Barbearia', 'Outro'];
