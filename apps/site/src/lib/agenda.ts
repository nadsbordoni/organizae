/**
 * Motor de disponibilidade — o cálculo de quais horários cabem num dia.
 *
 * REGRA DE OURO: nada aqui constrói `Date` para fazer conta de HORÁRIO. Um dia é
 * a string 'YYYY-MM-DD' e uma hora é o número de minutos desde a meia-noite,
 * sempre na hora de PAREDE do negócio. `Date` aparece só em conta de calendário
 * (que dia da semana cai, quantos dias entre duas datas) e sempre em UTC, onde
 * não existe horário de verão para deslocar o resultado.
 *
 * É isso que faz "14:00" continuar sendo 14:00 na virada do horário de verão, e
 * o mesmo código valer no build e no navegador de quem acessa de outro fuso.
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

/** Minúsculos, como manda o português: "6 de outubro". */
const MONTH_NAME = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
];

const MINUTES_IN_DAY = 1440;
const MS_IN_DAY = 86_400_000;

/** Faixa de minutos dentro de um dia: `[início, fim)`. */
export type Window = [number, number];

/* --- Horas e durações ------------------------------------------------------ */

export function toMinutes(time: ClockTime): number {
  const [hours, minutes] = time.split(':').map(Number);
  return hours * 60 + minutes;
}

export function toClock(minutes: number): ClockTime {
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

/** Duração como ela aparece na tela: '30min', '1h', '1h30'. */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest}min`;
  return rest ? `${hours}h${pad(rest)}` : `${hours}h`;
}

/* --- Preços ---------------------------------------------------------------- */

/**
 * 'R$ 1.234,56' → 123456 centavos. `undefined` quando não dá para ler.
 *
 * O preço é texto livre na configuração de propósito — "a partir de R$ 40" e
 * "sob consulta" são respostas legítimas de um salão. Somar só é possível
 * quando TODOS os escolhidos têm um número limpo; nos outros casos a tela mostra
 * os valores um a um, sem total. Inventar um total a partir de texto que não se
 * entende é pior do que não mostrar total nenhum.
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

/** Soma das durações — é ela que o motor usa para achar horário livre. */
export function totalDuration(
  services: ReadonlyArray<Pick<Service, 'durationMinutes'>>,
): number {
  return services.reduce((sum, service) => sum + service.durationMinutes, 0);
}

/* --- Datas ---------------------------------------------------------------- */

/**
 * Dias inteiros desde a época, em UTC.
 *
 * Toda conta com datas passa por aqui: comparar, ordenar e medir distância viram
 * aritmética de inteiros, sem fuso e sem horário de verão no meio.
 */
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

/**
 * `true` só para uma data que existe no calendário. O formato sozinho deixa
 * passar '2026-02-31', que `Date` vira 3 de março em silêncio.
 */
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

/**
 * "Hoje" e "agora" no fuso do NEGÓCIO, não no do aparelho de quem acessa.
 *
 * `Intl` é a única fonte de verdade sobre fuso que existe sem biblioteca — ele
 * já carrega a base de horário de verão do sistema. Consultamos uma vez só,
 * aqui, e o resto do módulo trabalha em hora de parede.
 */
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
    // `hourCycle` em vez de `hour12: false`: aquele produz '24' à meia-noite em
    // alguns motores, e 24:00 estouraria a conta de minutos.
    hourCycle: 'h23',
  }).formatToParts(clock);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? '0';

  return {
    date: `${get('year')}-${get('month')}-${get('day')}`,
    minutes: Number(get('hour')) * 60 + Number(get('minute')),
  };
}

/* --- Expediente ----------------------------------------------------------- */

export interface DaySchedule {
  hours: DayHours | null;
  /** Motivo do fechamento, quando vem de uma exceção. Ex: 'Feriado'. */
  reason?: string;
}

/** O expediente de uma data, já com as exceções aplicadas. */
export function scheduleFor(agenda: Agenda, date: IsoDate): DaySchedule {
  const exception = agenda.exceptions?.find((item) => item.date === date);
  if (exception) return { hours: exception.hours, reason: exception.reason };
  return { hours: agenda.hours[weekdayOf(date)] ?? null };
}

/**
 * Recorta `cut` das janelas recebidas.
 *
 * É a única operação de que o motor precisa: descontar o almoço e descontar um
 * atendimento já marcado são o MESMO cálculo. É por isso que ligar a agenda a um
 * servidor depois não muda nada aqui — muda só quantos cortes entram.
 */
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

/** Janelas em que o negócio está livre: expediente menos pausas e compromissos. */
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

/* --- Horários oferecidos -------------------------------------------------- */

export interface SlotQuery {
  agenda: Agenda;
  /** Só a duração importa — assim a função serve para simular, não só para exibir. */
  service: Pick<Service, 'durationMinutes'>;
  date: IsoDate;
  /**
   * Atendimentos já marcados no dia.
   *
   * ⚠️ HOJE CHEGA SEMPRE VAZIO: o fluxo público é pré-renderizado e ainda não
   * consulta o banco. Ligar a reserva é passar a lista aqui, sem reescrever o
   * cálculo.
   */
  busy?: readonly TimeRange[];
  /** "Agora" no fuso do negócio. Vem de `nowInBusinessTime()`. */
  now: { date: IsoDate; minutes: number };
}

/**
 * Horários em que o serviço CABE inteiro no dia.
 *
 * "Cabe inteiro" é a regra que faz a duração importar: com fechamento às 19:30,
 * um serviço de 2h para de ser oferecido às 17:30, e um de 30min segue até
 * 19:00. A cliente nunca vê um horário que o negócio não conseguiria cumprir.
 */
export function slotsFor({ agenda, service, date, busy, now }: SlotQuery): ClockTime[] {
  const daysAhead = dayNumber(date) - dayNumber(now.date);
  if (daysAhead < 0 || daysAhead > (agenda.horizonDays ?? AGENDA_DEFAULTS.horizonDays)) return [];

  const { hours } = scheduleFor(agenda, date);
  if (!hours) return [];

  const step = agenda.slotStepMinutes ?? AGENDA_DEFAULTS.slotStepMinutes;
  const opens = toMinutes(hours.opens);

  // Antecedência mínima traduzida para "minutos do relógio DESTE dia". Descontar
  // a distância em dias é o que faz a regra atravessar a meia-noite: às 22:00,
  // com 12h de antecedência, o dia seguinte só abre às 10:00.
  const earliest =
    now.minutes +
    (agenda.minNoticeHours ?? AGENDA_DEFAULTS.minNoticeHours) * 60 -
    daysAhead * MINUTES_IN_DAY;

  const slots: ClockTime[] = [];

  for (const [start, end] of freeWindows(hours, busy)) {
    // Alinha o começo à grade contada a partir da abertura: uma janela que sobra
    // em 12:20 passa a oferecer 12:30. Custa alguns minutos de agenda e evita
    // horário quebrado na tela — a grade é para a cliente ler, não para
    // aproveitar cada minuto do dia.
    const first = opens + Math.ceil((start - opens) / step) * step;

    for (let time = first; time + service.durationMinutes <= end; time += step) {
      if (time >= earliest) slots.push(toClock(time));
    }
  }

  return slots;
}

/** Atalho de leitura para o calendário, que só precisa saber se sobrou algo. */
export function hasSlots(query: SlotQuery): boolean {
  return slotsFor(query).length > 0;
}

/**
 * A primeira data com horário livre, dentro do horizonte. `undefined` quando não
 * há nenhuma — agenda cheia, ou serviço que não cabe em nenhum expediente.
 */
export function firstAvailableDate(query: Omit<SlotQuery, 'date'>): IsoDate | undefined {
  const horizon = query.agenda.horizonDays ?? AGENDA_DEFAULTS.horizonDays;

  for (let offset = 0; offset <= horizon; offset += 1) {
    const date = addDays(query.now.date, offset);
    if (hasSlots({ ...query, date })) return date;
  }

  return undefined;
}

/* --- Resumo da semana ----------------------------------------------------- */

/**
 * O expediente da semana em faixas legíveis, para o bloco de horário: agrupa
 * dias CONSECUTIVOS de mesmo expediente e devolve
 * `[{ days: 'Ter a Sex', time: '08:00 às 19:30' }]`.
 *
 * Existe para que o horário ANUNCIADO na página venha da mesma fonte que gera os
 * horários AGENDÁVEIS. Escritos à mão nos dois lugares, um dia a página promete
 * um expediente e a agenda oferece outro.
 *
 * A semana começa no domingo, como o calendário brasileiro, e as faixas fechadas
 * vão para o fim: quem lê quer ver primeiro quando o negócio abre.
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

/** Espaço inquebrável. Ver `describeDay()`. */
const NBSP = '\u00a0';

/**
 * O expediente de um dia em texto — com as pausas, porque anunciar
 * "08:00 às 19:30" tendo almoço no meio faz a cliente tentar marcar às 12:30 e
 * não encontrar nada, sem entender por quê.
 *
 * `NBSP` liga cada faixa de propósito: com duas faixas o texto passa da largura
 * da linha, e a quebra precisa cair no " e ", nunca no meio de "08:00 às 12:00".
 * É o que substitui o `white-space: nowrap` que o bloco de horário usava quando
 * só existia uma faixa por dia. Escrito como escape para ninguém "limpar" um
 * caractere invisível sem saber que ele fazia algo.
 */
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

/* --- Validação da configuração -------------------------------------------- */

/**
 * Para o build quando a agenda está mal configurada.
 *
 * Sem isto o erro só aparece no celular da cliente: passo de grade negativo
 * trava o navegador, '8h00' some com o dia e `closes` antes de `opens` fecha o
 * dia em silêncio.
 */
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
