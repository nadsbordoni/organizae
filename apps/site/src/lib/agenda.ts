/**
 * Motor de disponibilidade. REGRA: NÃO usar `Date` em conta de HORÁRIO; dia é 'YYYY-MM-DD' e hora é
 * minutos desde a meia-noite, na hora de PAREDE do negócio. `Date` só em conta de calendário e
 * sempre em UTC, onde não há horário de verão para deslocar o resultado.
 */

import type {
  Agenda,
  ClockTime,
  DayHours,
  IsoDate,
  Service,
  TimeRange,
  Weekday,
} from '@/types/agenda';

export const AGENDA_DEFAULTS = {
  slotStepMinutes: 30,
  minNoticeHours: 12,
  horizonDays: 60,
} as const;

/** Índice = `getUTCDay()`: 0 é domingo. A ordem também é a do calendário. */
export const WEEKDAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] as const;

const WEEKDAY_NAME: Record<Weekday, { full: string; short: string; initial: string }> = {
  sun: { full: 'Domingo', short: 'Dom', initial: 'D' },
  mon: { full: 'Segunda', short: 'Seg', initial: 'S' },
  tue: { full: 'Terça', short: 'Ter', initial: 'T' },
  wed: { full: 'Quarta', short: 'Qua', initial: 'Q' },
  thu: { full: 'Quinta', short: 'Qui', initial: 'Q' },
  fri: { full: 'Sexta', short: 'Sex', initial: 'S' },
  sat: { full: 'Sábado', short: 'Sáb', initial: 'S' },
};

const MONTH_NAME = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
];

const MINUTES_IN_DAY = 1440;
const MS_IN_DAY = 86_400_000;

/** Faixa de minutos dentro de um dia: `[início, fim)`. */
export type Window = [number, number];

export function toMinutes(time: ClockTime): number {
  const [hours, minutes] = time.split(':').map(Number);
  return hours * 60 + minutes;
}

export function toClock(minutes: number): ClockTime {
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

/** Ex: '30min', '1h', '1h30'. */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}min`;
  return rest ? `${hours}h${pad(rest)}` : `${hours}h`;
}

/**
 * 'R$ 1.234,56' → 123456 centavos; `undefined` quando não dá para ler. Preço é texto livre de
 * propósito ("a partir de R$ 40", "sob consulta"): sem número limpo, NÃO se inventa total.
 */
export function parsePrice(text: string | undefined): number | undefined {
  if (!text) return undefined;

  // Formato brasileiro: ponto separa milhar, vírgula separa centavo.
  const match = text.match(/^\s*R?\$?\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?\s*$/);
  if (!match) return undefined;

  return Number(match[1].replace(/\./g, '')) * 100 + Number(match[2] ?? 0);
}

export function formatPrice(cents: number): string {
  const reais = Math.floor(cents / 100).toLocaleString('pt-BR');
  return `R$ ${reais},${pad(cents % 100)}`;
}

/** Soma dos preços, ou `undefined` se algum serviço não tiver valor legível. */
export function totalPrice(services: ReadonlyArray<Pick<Service, 'price'>>): string | undefined {
  let total = 0;

  for (const service of services) {
    const cents = parsePrice(service.price);
    if (cents === undefined) return undefined;
    total += cents;
  }

  return formatPrice(total);
}

export function totalDuration(
  services: ReadonlyArray<Pick<Service, 'durationMinutes'>>,
): number {
  return services.reduce((sum, service) => sum + service.durationMinutes, 0);
}

/** Dias inteiros desde 1970-01-01 em UTC: conta de datas vira aritmética de inteiros, sem fuso. */
export function dayNumber(date: IsoDate): number {
  const [year, month, day] = date.split('-').map(Number);
  return Date.UTC(year, month - 1, day) / MS_IN_DAY;
}

export function fromDayNumber(days: number): IsoDate {
  const at = new Date(days * MS_IN_DAY);
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
}

export function addDays(date: IsoDate, days: number): IsoDate {
  return fromDayNumber(dayNumber(date) + days);
}

export function toIsoDate(year: number, month: number, day: number): IsoDate {
  return `${year}-${pad(month)}-${pad(day)}`;
}

export function weekdayOf(date: IsoDate): Weekday {
  // `dayNumber` conta a partir de 1970-01-01, que caiu numa quinta (índice 4).
  return WEEKDAYS[(((dayNumber(date) + 4) % 7) + 7) % 7];
}

/** Só data que existe: o formato sozinho deixa passar '2026-02-31', que `Date` vira 3 de março. */
export function isIsoDate(value: string): value is IsoDate {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && fromDayNumber(dayNumber(value)) === value;
}

/** Ex: 'Quarta, 14 de agosto de 2026'. */
export function formatLongDate(date: IsoDate): string {
  const [year, month, day] = date.split('-').map(Number);
  return `${WEEKDAY_NAME[weekdayOf(date)].full}, ${day} de ${MONTH_NAME[month - 1]} de ${year}`;
}

/** Ex: 'Quarta, 14 de agosto'. */
export function formatShortDate(date: IsoDate): string {
  const [, month, day] = date.split('-').map(Number);
  return `${WEEKDAY_NAME[weekdayOf(date)].full}, ${day} de ${MONTH_NAME[month - 1]}`;
}

/** Ex: 'Agosto de 2026' — cabeçalho, por isso a maiúscula. */
export function formatMonth(year: number, month: number): string {
  const name = MONTH_NAME[month - 1];
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} de ${year}`;
}

/** Cabeçalho do calendário, começando no domingo: D S T Q Q S S. */
export function weekdayInitials(): string[] {
  return WEEKDAYS.map((day) => WEEKDAY_NAME[day].initial);
}

/** "Hoje" e "agora" no fuso do NEGÓCIO, não no do aparelho de quem acessa. */
export function nowInBusinessTime(
  timezone: string,
  clock: Date = new Date(),
): { date: IsoDate; minutes: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    // NÃO trocar por `hour12: false`: em alguns motores dá '24' à meia-noite e estoura a conta.
    hourCycle: 'h23',
  }).formatToParts(clock);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? '0';

  return {
    date: `${get('year')}-${get('month')}-${get('day')}`,
    minutes: Number(get('hour')) * 60 + Number(get('minute')),
  };
}

export interface DaySchedule {
  hours: DayHours | null;
  /** Só quando vem de uma exceção. Ex: 'Feriado'. */
  reason?: string;
}

/** Já com as exceções aplicadas. */
export function scheduleFor(agenda: Agenda, date: IsoDate): DaySchedule {
  const exception = agenda.exceptions?.find((item) => item.date === date);
  if (exception) return { hours: exception.hours, reason: exception.reason };
  return { hours: agenda.hours[weekdayOf(date)] ?? null };
}

function subtract(windows: Window[], cut: Window): Window[] {
  const result: Window[] = [];

  for (const [start, end] of windows) {
    if (cut[1] <= start || cut[0] >= end) {
      result.push([start, end]);
      continue;
    }
    if (cut[0] > start) result.push([start, cut[0]]);
    if (cut[1] < end) result.push([cut[1], end]);
  }

  return result;
}

export function freeWindows(hours: DayHours, busy: readonly TimeRange[] = []): Window[] {
  let windows: Window[] = [[toMinutes(hours.opens), toMinutes(hours.closes)]];

  for (const pause of hours.breaks ?? []) {
    windows = subtract(windows, [toMinutes(pause.from), toMinutes(pause.to)]);
  }
  for (const appointment of busy) {
    windows = subtract(windows, [toMinutes(appointment.from), toMinutes(appointment.to)]);
  }

  return windows.filter(([start, end]) => end > start);
}

export interface SlotQuery {
  agenda: Agenda;
  service: Pick<Service, 'durationMinutes'>;
  date: IsoDate;
  /** HOJE CHEGA SEMPRE VAZIO: o fluxo público é pré-renderizado e ainda não consulta o banco. */
  busy?: readonly TimeRange[];
  /** "Agora" no fuso do negócio. Vem de `nowInBusinessTime()`. */
  now: { date: IsoDate; minutes: number };
}

/** Horários em que o serviço CABE inteiro: fechando às 19:30, um de 2h para às 17:30. */
export function slotsFor({ agenda, service, date, busy, now }: SlotQuery): ClockTime[] {
  const daysAhead = dayNumber(date) - dayNumber(now.date);
  if (daysAhead < 0 || daysAhead > (agenda.horizonDays ?? AGENDA_DEFAULTS.horizonDays)) return [];

  const { hours } = scheduleFor(agenda, date);
  if (!hours) return [];

  const step = agenda.slotStepMinutes ?? AGENDA_DEFAULTS.slotStepMinutes;
  const opens = toMinutes(hours.opens);

  // Antecedência em minutos do relógio DESTE dia; descontar os dias faz a regra atravessar a
  // meia-noite (às 22:00, com 12h, o dia seguinte só abre às 10:00).
  const earliest =
    now.minutes +
    (agenda.minNoticeHours ?? AGENDA_DEFAULTS.minNoticeHours) * 60 -
    daysAhead * MINUTES_IN_DAY;

  const slots: ClockTime[] = [];

  for (const [start, end] of freeWindows(hours, busy)) {
    // Alinha à grade contada da abertura (sobra em 12:20 oferece 12:30): perde alguns
    // minutos de agenda, mas evita horário quebrado na tela.
    const first = opens + Math.ceil((start - opens) / step) * step;

    for (let time = first; time + service.durationMinutes <= end; time += step) {
      if (time >= earliest) slots.push(toClock(time));
    }
  }

  return slots;
}

export function hasSlots(query: SlotQuery): boolean {
  return slotsFor(query).length > 0;
}

/** `undefined` sem vaga no horizonte: agenda cheia, ou serviço que não cabe em nenhum expediente. */
export function firstAvailableDate(query: Omit<SlotQuery, 'date'>): IsoDate | undefined {
  const horizon = query.agenda.horizonDays ?? AGENDA_DEFAULTS.horizonDays;

  for (let offset = 0; offset <= horizon; offset += 1) {
    const date = addDays(query.now.date, offset);
    if (hasSlots({ ...query, date })) return date;
  }

  return undefined;
}

/**
 * `[{ days: 'Ter a Sex', time: '08:00 às 19:30' }]`, dias fechados no fim. Deriva da agenda para
 * o horário ANUNCIADO na página NÃO divergir do AGENDÁVEL.
 */
export function weeklySummary(agenda: Agenda): Array<{ days: string; time: string }> {
  const groups: Array<{ days: Weekday[]; time: string }> = [];

  for (const day of WEEKDAYS) {
    const time = describeDay(agenda.hours[day]);
    const previous = groups.at(-1);

    if (previous && previous.time === time) previous.days.push(day);
    else groups.push({ days: [day], time });
  }

  return [
    ...groups.filter((group) => group.time !== CLOSED),
    ...groups.filter((group) => group.time === CLOSED),
  ].map((group) => ({ days: describeDays(group.days), time: group.time }));
}

const CLOSED = 'Fechado';

/** Espaço inquebrável, em escape de propósito: a quebra cai no " e ", NUNCA dentro de "08:00 às 12:00". */
const NBSP = '\u00a0';

/** Com as pausas: anunciar "08:00 às 19:30" com almoço no meio faz a cliente procurar vaga que não há. */
function describeDay(hours: DayHours | undefined): string {
  if (!hours) return CLOSED;

  return freeWindows(hours)
    .map(([start, end]) => `${toClock(start)}${NBSP}às${NBSP}${toClock(end)}`)
    .join(' e ');
}

/** 'Sábado' sozinho, 'Dom e Seg' em par, 'Ter a Sex' de três em diante. */
function describeDays(days: Weekday[]): string {
  const first = WEEKDAY_NAME[days[0]];
  if (days.length === 1) return first.full;

  const last = WEEKDAY_NAME[days[days.length - 1]];
  return days.length === 2
    ? `${first.short} e ${last.short}`
    : `${first.short} a ${last.short}`;
}

/** Quebra o BUILD com agenda mal configurada; senão o erro só aparece no celular da cliente. */
export function assertValidAgenda(agenda: Agenda, label: string): void {
  const problems: string[] = [];
  const clock = /^([01]\d|2[0-3]):[0-5]\d$/;

  const checkHours = (where: string, hours: DayHours) => {
    if (!clock.test(hours.opens) || !clock.test(hours.closes)) {
      problems.push(`${where}: use HH:MM em opens/closes`);
      return;
    }
    if (toMinutes(hours.opens) >= toMinutes(hours.closes)) {
      problems.push(`${where}: closes precisa ser depois de opens`);
    }
    for (const pause of hours.breaks ?? []) {
      if (!clock.test(pause.from) || !clock.test(pause.to)) {
        problems.push(`${where}: use HH:MM nas pausas`);
      } else if (
        toMinutes(pause.from) >= toMinutes(pause.to) ||
        toMinutes(pause.from) < toMinutes(hours.opens) ||
        toMinutes(pause.to) > toMinutes(hours.closes)
      ) {
        problems.push(`${where}: pausa ${pause.from}–${pause.to} fora do expediente ou invertida`);
      }
    }
  };

  const positiveInteger = (name: string, value: number | undefined, allowZero = false) => {
    if (value === undefined) return;
    if (!Number.isInteger(value) || value < (allowZero ? 0 : 1)) {
      problems.push(`${name} precisa ser um inteiro ${allowZero ? '≥ 0' : '> 0'}`);
    }
  };

  positiveInteger('slotStepMinutes', agenda.slotStepMinutes);
  positiveInteger('minNoticeHours', agenda.minNoticeHours, true);
  positiveInteger('horizonDays', agenda.horizonDays);

  for (const day of WEEKDAYS) {
    const hours = agenda.hours[day];
    if (hours) checkHours(day, hours);
  }

  for (const exception of agenda.exceptions ?? []) {
    if (!isIsoDate(exception.date)) problems.push(`exceção ${exception.date}: data inexistente`);
    if (exception.hours) checkHours(`exceção ${exception.date}`, exception.hours);
  }

  const ids = new Set<string>();
  for (const category of agenda.categories) {
    for (const service of category.services) {
      if (ids.has(service.id)) problems.push(`serviço '${service.id}' repetido`);
      ids.add(service.id);
      positiveInteger(`duração de '${service.id}'`, service.durationMinutes);
    }
  }

  if (problems.length) {
    throw new Error(`Agenda de '${label}' inválida:\n  - ${problems.join('\n  - ')}`);
  }
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}
