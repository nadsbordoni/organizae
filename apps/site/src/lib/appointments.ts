import type { Agenda, DayHours, IsoDate, Weekday } from '@/types/agenda';
import type { AppointmentRow } from '@/types/painel';
import { WEEKDAYS, addDays, formatPrice, nowInBusinessTime, toClock } from './agenda';
import { api } from './api';

/** Agenda do painel com os dados do negócio logado (`GET /appointments`, `/business-hours`, `/services`). */

export interface AppointmentResponse {
  id: string;
  service_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  notes: string | null;
  starts_at: string;
  ends_at: string;
  status: 'PENDING' | 'CONFIRMED' | 'CANCELLED' | 'BLOCKED';
  source: 'ONLINE' | 'PANEL';
  created_at: string;
}

interface BusinessHourResponse {
  /** 0 = segunda, como `date.weekday()` do Python. */
  weekday: number;
  opens_at: string;
  closes_at: string;
}

interface ServiceResponse {
  id: string;
  name: string;
  price: string;
  duration_minutes: number;
}

const STATUS = { PENDING: 'pending', CONFIRMED: 'confirmed', CANCELLED: 'cancelled' } as const;

/** Grade de exibição enquanto o negócio não cadastrou o horário de funcionamento. */
const DISPLAY_HOURS: DayHours = { opens: '08:00', closes: '18:00' };

/**
 * A API não tem "atendido": confirmado que já terminou conta como atendido, que é o que o histórico
 * do cliente e os totais contam.
 */
function statusOf(appointment: AppointmentResponse): AppointmentRow['status'] {
  if (appointment.status === 'CONFIRMED' && Date.parse(appointment.ends_at) <= Date.now()) return 'done';
  return STATUS[appointment.status as keyof typeof STATUS];
}

export function toRow(appointment: AppointmentResponse, timezone: string): AppointmentRow | undefined {
  if (appointment.status === 'BLOCKED') return undefined;
  const start = nowInBusinessTime(timezone, new Date(appointment.starts_at));
  return {
    id: appointment.id,
    tenant_slug: '',
    date: start.date,
    start_time: toClock(start.minutes),
    duration_min: Math.round((Date.parse(appointment.ends_at) - Date.parse(appointment.starts_at)) / 60_000),
    service_ids: JSON.stringify(appointment.service_id ? [appointment.service_id] : []),
    client_name: appointment.customer_name ?? 'Sem nome',
    client_phone: appointment.customer_phone,
    notes: appointment.notes,
    status: statusOf(appointment),
    origin: appointment.source === 'ONLINE' ? 'site' : 'panel',
    created_at: appointment.created_at,
    updated_at: appointment.created_at,
  };
}

/**
 * Atendimentos de `from` a `to` (inclusive), no calendário do negócio. Pede um dia a mais de cada
 * lado em UTC e filtra pela data local: assim o fuso não corta atendimento da noite nem da madrugada.
 */
export async function appointmentsBetween(token: string, from: IsoDate, to: IsoDate, timezone: string): Promise<AppointmentRow[]> {
  const query = new URLSearchParams({
    starts_at: `${addDays(from, -1)}T00:00:00Z`,
    ends_at: `${addDays(to, 2)}T00:00:00Z`,
  });
  const appointments = await api<AppointmentResponse[]>(`/appointments?${query}`, { token });
  return appointments
    .map((appointment) => toRow(appointment, timezone))
    .filter((row): row is AppointmentRow => row !== undefined && row.date >= from && row.date <= to)
    .sort((a, b) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`));
}

/** Almoço é cadastrado como duas janelas no mesmo dia; aqui vira expediente com pausa. */
function toWeekHours(windows: BusinessHourResponse[]): Partial<Record<Weekday, DayHours>> {
  const hours: Partial<Record<Weekday, DayHours>> = {};
  for (let weekday = 0; weekday < 7; weekday++) {
    const day = windows
      .filter((window) => window.weekday === weekday)
      .map((window) => ({ from: window.opens_at.slice(0, 5), to: window.closes_at.slice(0, 5) }))
      .sort((a, b) => a.from.localeCompare(b.from));
    if (!day.length) continue;
    const breaks = day.slice(1).map((window, index) => ({ from: day[index]!.to, to: window.from }));
    hours[WEEKDAYS[(weekday + 1) % 7]!] = {
      opens: day[0]!.from,
      closes: day.at(-1)!.to,
      ...(breaks.length ? { breaks } : {}),
    };
  }
  return hours;
}

/**
 * A agenda do site com o horário e os serviços do banco. `hoursMissing`: o negócio ainda não
 * cadastrou o horário, e a grade usa um expediente só para desenhar (seg a sáb, 08h às 18h).
 */
export async function businessAgenda(token: string, base: Agenda | undefined): Promise<{ agenda: Agenda; hoursMissing: boolean }> {
  const [windows, services] = await Promise.all([
    api<BusinessHourResponse[]>('/business-hours', { token }),
    api<ServiceResponse[]>('/services', { token }),
  ]);
  const hoursMissing = windows.length === 0;
  const hours = hoursMissing
    ? Object.fromEntries(WEEKDAYS.filter((day) => day !== 'sun').map((day) => [day, DISPLAY_HOURS]))
    : toWeekHours(windows);

  return {
    hoursMissing,
    agenda: {
      timezone: base?.timezone ?? 'America/Sao_Paulo',
      request: base?.request ?? { via: 'whatsapp', phone: '' },
      hours,
      exceptions: [],
      categories: [
        {
          id: 'servicos',
          name: 'Serviços',
          services: services.map((service) => ({
            id: service.id,
            name: service.name,
            durationMinutes: service.duration_minutes,
            price: formatPrice(Math.round(Number(service.price) * 100)),
          })),
        },
      ],
    },
  };
}
