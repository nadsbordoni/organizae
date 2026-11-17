import { addDays, dayNumber, toClock, toMinutes } from './agenda';
import type { Agenda, IsoDate } from '@/types/agenda';
import type { AppointmentRow } from '@/types/painel';

/** Regras da área da cliente: o que já passou, o que vem e até quando dá para cancelar sozinha. */

export const DEFAULT_CANCEL_NOTICE_HOURS = 12;

type Now = { date: IsoDate; minutes: number };

/** Minutos de agora até o início do atendimento (negativo se já começou). */
export const minutesUntil = (row: Pick<AppointmentRow, 'date' | 'start_time'>, now: Now) =>
  (dayNumber(row.date) - dayNumber(now.date)) * 24 * 60 + toMinutes(row.start_time) - now.minutes;

export const isUpcoming = (row: AppointmentRow, now: Now) =>
  row.status !== 'cancelled' && row.status !== 'done' && minutesUntil(row, now) > 0;

export interface CancelRule {
  allowed: boolean;
  hours: number;
  /** Último momento para cancelar pela área da cliente. */
  until: { date: IsoDate; time: string };
}

export function cancelRule(row: AppointmentRow, agenda: Agenda | undefined, now: Now): CancelRule {
  const hours = agenda?.cancelNoticeHours ?? DEFAULT_CANCEL_NOTICE_HOURS;
  const startAbsolute = dayNumber(row.date) * 24 * 60 + toMinutes(row.start_time) - hours * 60;
  const day = Math.floor(startAbsolute / (24 * 60));
  const date = addDays(row.date, day - dayNumber(row.date));
  return {
    allowed: minutesUntil(row, now) > hours * 60,
    hours,
    until: { date, time: toClock(startAbsolute - day * 24 * 60) },
  };
}
