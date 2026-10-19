import { addDays, nowInBusinessTime, weekdayOf } from './agenda';
import type { AppointmentStatus } from './dashboard-status';
import type { AgendaException, IsoDate } from '@/types/agenda';
import type { AppointmentRow, AuthenticatedUser } from '@/types/painel';

/**
 * Dados FICTÍCIOS do painel, no lugar do back-end. Todo o painel lê daqui.
 * ⚠️ Sai quando a API existir: `forTenant` vira chamadas HTTP com o mesmo
 * formato de retorno, e `usuarioExemplo` vira a sessão de verdade.
 */

export const usuarioExemplo: AuthenticatedUser = {
  userId: 1,
  tenantSlug: 'exemplo',
  email: 'joana@exemplo.com',
  name: 'Joana',
  sessionId: 'exemplo',
};

/** Modelo de um dia de trabalho. Os ids são serviços de `config/sites/_exemplo.ts`. */
const MODELO = [
  { hora: '09:00', min: 120, servicos: ['alongamento'], nome: 'Marina Costa' },
  { hora: '11:00', min: 45, servicos: ['esmaltacao'], nome: 'Beatriz Lima' },
  { hora: '13:00', min: 90, servicos: ['manutencao'], nome: 'Camila Rocha' },
  { hora: '15:00', min: 60, servicos: ['pedicure'], nome: 'Fernanda Alves' },
  { hora: '16:30', min: 90, servicos: ['manutencao'], nome: 'Juliana Souza' },
];

/** Estado conforme o dia seja passado, hoje ou futuro; o 3º atendimento passado foi cancelado. */
function statusDe(indice: number, quando: 'passado' | 'hoje' | 'futuro'): AppointmentStatus {
  if (quando === 'passado') return indice === 2 ? 'cancelled' : 'done';
  if (quando === 'hoje') return (['done', 'done', 'confirmed', 'confirmed', 'pending'] as const)[indice]!;
  return indice % 2 === 0 ? 'confirmed' : 'pending';
}

function doDia(date: IsoDate, hoje: IsoDate): AppointmentRow[] {
  if (weekdayOf(date) === 'sun') return [];
  const quando = date < hoje ? 'passado' : date === hoje ? 'hoje' : 'futuro';
  const dia = Number(date.slice(8, 10));

  return MODELO.map((m, i) => ({
    id: dia * 10 + i,
    tenant_slug: usuarioExemplo.tenantSlug,
    date,
    start_time: m.hora,
    duration_min: m.min,
    service_ids: JSON.stringify(m.servicos),
    client_name: m.nome,
    client_phone: null,
    notes: null,
    status: statusDe(i, quando),
    origin: i % 2 === 0 ? ('site' as const) : ('panel' as const),
    created_at: `${date}T08:00:00Z`,
    updated_at: `${date}T08:00:00Z`,
  }));
}

export function forTenant(_tenantSlug: string) {
  const hoje = nowInBusinessTime('America/Sao_Paulo').date;

  return {
    async appointmentsOn(date: IsoDate): Promise<AppointmentRow[]> {
      return doDia(date, hoje);
    },

    async appointmentsBetween(from: IsoDate, to: IsoDate): Promise<AppointmentRow[]> {
      const rows: AppointmentRow[] = [];
      for (let d = from; d <= to; d = addDays(d, 1)) rows.push(...doDia(d, hoje));
      return rows;
    },

    async exceptionsBetween(_from: IsoDate, _to: IsoDate): Promise<AgendaException[]> {
      return [];
    },
  };
}
