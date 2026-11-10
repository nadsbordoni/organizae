import { addDays, nowInBusinessTime, weekdayOf } from './agenda';
import type { AppointmentStatus } from './dashboard-status';
import type { AgendaException, IsoDate } from '@/types/agenda';
import type { AgendaNotification, AppointmentRow, AuthenticatedUser } from '@/types/painel';

/**
 * Dados FICTÍCIOS do painel, no lugar do back-end. Saem quando a API existir: `forTenant`
 * vira chamadas HTTP com o mesmo formato de retorno, e `usuarioExemplo` vira a sessão de verdade.
 */

export const usuarioExemplo: AuthenticatedUser = {
  userId: 1,
  tenantSlug: 'exemplo',
  email: 'joana@exemplo.com',
  name: 'Joana',
  sessionId: 'exemplo',
};

/** Um dia de trabalho. Os ids são serviços de `config/sites/_exemplo.ts`. */
const MODELO = [
  {
    hora: '09:00',
    min: 120,
    servicos: ['alongamento'],
    nome: 'Marina Costa',
    telefone: '5511987650101',
    obs: 'Prefere formato amendoado, comprimento médio.',
  },
  { hora: '11:00', min: 45, servicos: ['esmaltacao'], nome: 'Beatriz Lima', telefone: null, obs: null },
  {
    hora: '13:00',
    min: 90,
    servicos: ['manutencao'],
    nome: 'Camila Rocha',
    telefone: '5511987650303',
    obs: 'Alergia a acetona: usar removedor sem acetona.',
  },
  { hora: '15:00', min: 60, servicos: ['pedicure'], nome: 'Fernanda Alves', telefone: '5511987650404', obs: null },
  {
    hora: '16:30',
    min: 90,
    servicos: ['manutencao'],
    nome: 'Juliana Souza',
    telefone: '5511987650505',
    obs: 'Primeira vez no estúdio. Pediu indicação de cor.',
  },
];

function statusDe(indice: number, quando: 'passado' | 'hoje' | 'futuro'): AppointmentStatus {
  if (quando === 'passado') return indice === 2 ? 'cancelled' : 'done';
  if (quando === 'hoje') return (['done', 'done', 'confirmed', 'confirmed', 'pending'] as const)[indice]!;
  return indice % 2 === 0 ? 'confirmed' : 'pending';
}

/** Próximo dia depois de `hoje` em que o exemplo atende (não abre aos domingos). */
function proximoDiaUtil(hoje: IsoDate, depois = 1): IsoDate {
  let date = hoje;
  for (let n = 0; n < depois; ) {
    date = addDays(date, 1);
    if (weekdayOf(date) !== 'sun') n++;
  }
  return date;
}

function doDia(date: IsoDate, hoje: IsoDate): AppointmentRow[] {
  if (weekdayOf(date) === 'sun') return [];
  const quando = date < hoje ? 'passado' : date === hoje ? 'hoje' : 'futuro';
  // O 4º atendimento do próximo dia útil é o cancelamento dos avisos de demonstração.
  const cancelado = date === proximoDiaUtil(hoje) ? 3 : -1;
  const dia = Number(date.slice(8, 10));

  return MODELO.map((m, i) => ({
    id: dia * 10 + i,
    tenant_slug: usuarioExemplo.tenantSlug,
    date,
    start_time: m.hora,
    duration_min: m.min,
    service_ids: JSON.stringify(m.servicos),
    client_name: m.nome,
    client_phone: m.telefone,
    notes: m.obs,
    status: i === cancelado ? 'cancelled' : statusDe(i, quando),
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

/**
 * Números de DEMONSTRAÇÃO, iguais ao protótipo (quadro 05). NÃO saem dos agendamentos acima e
 * não batem com eles, a pedido. Saem quando a API devolver o resumo do mês.
 */
export const resumoDemonstracao = {
  faturamentoCentavos: 2_143_000,
  variacaoFaturamento: 12.4,
  agendamentos: 148,
  ocupacao: 92,
  novosClientes: 24,
  novosNoMes: 8,
  taxaRetorno: 76,
  /** Últimos 7 meses, do mais antigo ao atual, em reais. */
  movimento: [
    { receitas: 4_800, despesas: 1_400 },
    { receitas: 9_200, despesas: 5_600 },
    { receitas: 15_400, despesas: 4_600 },
    { receitas: 13_100, despesas: 7_500 },
    { receitas: 18_900, despesas: 8_200 },
    { receitas: 19_100, despesas: 10_800 },
    { receitas: 21_430, despesas: 11_300 },
  ],
  /** Ids de `config/sites/_exemplo.ts`; o valor sai do preço do catálogo. */
  servicosMaisAgendados: [
    { id: 'manutencao', agendamentos: 58 },
    { id: 'alongamento', agendamentos: 41 },
    { id: 'esmaltacao', agendamentos: 29 },
  ],
};

/** Avisos de DEMONSTRAÇÃO, como no protótipo (quadro 05), apontando para atendimentos do exemplo. */
export function avisosDemonstracao(hoje: IsoDate): AgendaNotification[] {
  const amanha = doDia(proximoDiaUtil(hoje), hoje);
  const depois = doDia(proximoDiaUtil(hoje, 2), hoje);
  return [
    { id: 'novo-1', kind: 'created', at: '13:15', read: false, row: amanha[0]! },
    { id: 'cancelado-1', kind: 'cancelled', at: '12:40', read: false, row: amanha[3]! },
    { id: 'novo-2', kind: 'created', at: '11:10', read: true, row: depois[1]! },
  ];
}
