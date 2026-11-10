import { addDays, nowInBusinessTime, weekdayOf } from './agenda';
import type { AppointmentStatus } from './dashboard-status';
import type { AgendaException, IsoDate } from '@/types/agenda';
import type { AgendaNotification, AppointmentRow, AuthenticatedUser, ClientRow } from '@/types/painel';

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

    async clients(): Promise<ClientRow[]> {
      return CLIENTS.map((c) => toClientRow(c, hoje)).sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));
    },

    async client(id: string): Promise<ClientRow | undefined> {
      const found = CLIENTS.find((c) => c.id === id);
      return found && toClientRow(found, hoje);
    },

    /** Do mais recente ao mais antigo, como `GET /clients/{id}/appointments`. */
    async clientAppointments(id: string): Promise<AppointmentRow[]> {
      const index = CLIENTS.findIndex((c) => c.id === id);
      return index < 0 ? [] : clientHistory(CLIENTS[index]!, index, hoje);
    },
  };
}

interface DemoClient {
  id: string;
  name: string;
  phone: string;
  email: string | null;
  notes: string | null;
  birthDate: string | null;
  referral: string | null;
  optIn: boolean;
  /** Dias desde o cadastro de quem ainda não foi atendido; os demais se cadastram no primeiro atendimento. */
  since?: number;
  /** Tamanho do histórico, dias desde o último atendimento e intervalo entre eles. */
  visits: number;
  lastDaysAgo: number;
  everyDays: number;
  /** Ids de `config/sites/_exemplo.ts`, em rodízio. */
  services: string[];
  /** Posições do histórico que foram canceladas. */
  cancelled?: number[];
}

const DURATION: Record<string, number> = { alongamento: 120, manutencao: 90, esmaltacao: 45, pedicure: 60 };

/**
 * Carteira de DEMONSTRAÇÃO. As datas contam para trás a partir de hoje, para "há 14 dias" não
 * envelhecer. O histórico é próprio: a agenda acima repete o mesmo dia e daria visitas diárias.
 */
const CLIENTS: DemoClient[] = [
  {
    id: 'marina-costa',
    name: 'Marina Costa',
    phone: '5511987650101',
    email: 'marina.costa@email.com',
    notes: 'Prefere horários à tarde. Formato amendoado, comprimento médio.',
    birthDate: '1994-08-12',
    referral: 'Instagram',
    optIn: true,
    visits: 13,
    lastDaysAgo: 14,
    everyDays: 32,
    services: ['manutencao', 'manutencao', 'alongamento', 'pedicure'],
    cancelled: [5],
  },
  {
    id: 'beatriz-lima',
    name: 'Beatriz Lima',
    phone: '5511987650202',
    email: null,
    notes: null,
    birthDate: null,
    referral: 'Indicação',
    optIn: false,
    visits: 6,
    lastDaysAgo: 9,
    everyDays: 40,
    services: ['esmaltacao'],
  },
  {
    id: 'camila-rocha',
    name: 'Camila Rocha',
    phone: '5511987650303',
    email: 'camila.rocha@email.com',
    notes: 'Alergia a acetona: usar removedor sem acetona.',
    birthDate: '1988-03-02',
    referral: 'Google',
    optIn: true,
    visits: 10,
    lastDaysAgo: 21,
    everyDays: 30,
    services: ['manutencao', 'manutencao', 'esmaltacao'],
  },
  {
    id: 'fernanda-alves',
    name: 'Fernanda Alves',
    phone: '5511987650404',
    email: null,
    notes: null,
    birthDate: '1991-11-23',
    referral: 'Instagram',
    optIn: true,
    visits: 5,
    lastDaysAgo: 28,
    everyDays: 35,
    services: ['pedicure', 'esmaltacao'],
  },
  {
    id: 'juliana-souza',
    name: 'Juliana Souza',
    phone: '5511987650505',
    email: 'juliana.souza@email.com',
    notes: 'Primeira vez no estúdio. Pediu indicação de cor.',
    birthDate: null,
    referral: 'Instagram',
    optIn: true,
    since: 3,
    visits: 0,
    lastDaysAgo: 0,
    everyDays: 0,
    services: [],
  },
  {
    id: 'julia-mendes',
    name: 'Júlia Mendes',
    phone: '5511987650606',
    email: 'julia.mendes@email.com',
    notes: null,
    birthDate: '2000-06-15',
    referral: 'Indicação',
    optIn: true,
    visits: 1,
    lastDaysAgo: 12,
    everyDays: 0,
    services: ['alongamento'],
  },
  {
    id: 'bruna-lima',
    name: 'Bruna Lima',
    phone: '5511987650707',
    email: 'bruna.lima@email.com',
    notes: 'Gosta de cores nude.',
    birthDate: '1985-01-30',
    referral: 'WhatsApp',
    optIn: true,
    visits: 15,
    lastDaysAgo: 6,
    everyDays: 21,
    services: ['manutencao', 'esmaltacao', 'manutencao', 'pedicure'],
  },
  {
    id: 'camila-nunes',
    name: 'Camila Nunes',
    phone: '5511987650808',
    email: null,
    notes: null,
    birthDate: null,
    referral: 'Instagram',
    optIn: false,
    visits: 8,
    lastDaysAgo: 33,
    everyDays: 40,
    services: ['esmaltacao', 'pedicure'],
  },
  {
    id: 'sofia-ramos',
    name: 'Sofia Ramos',
    phone: '5511987650909',
    email: 'sofia.ramos@email.com',
    notes: null,
    birthDate: '1997-09-04',
    referral: 'Google',
    optIn: true,
    visits: 4,
    lastDaysAgo: 45,
    everyDays: 50,
    services: ['pedicure'],
  },
  {
    id: 'patricia-melo',
    name: 'Patrícia Melo',
    phone: '5511987651010',
    email: null,
    notes: 'Prefere ser lembrada por ligação.',
    birthDate: null,
    referral: 'Indicação',
    optIn: false,
    visits: 5,
    lastDaysAgo: 64,
    everyDays: 45,
    services: ['manutencao'],
  },
  {
    id: 'luiza-prado',
    name: 'Luiza Prado',
    phone: '5511987651111',
    email: 'luiza.prado@email.com',
    notes: null,
    birthDate: '1993-04-18',
    referral: 'Instagram',
    optIn: true,
    visits: 4,
    lastDaysAgo: 71,
    everyDays: 45,
    services: ['esmaltacao', 'manutencao'],
  },
  {
    id: 'ana-souza',
    name: 'Ana Souza',
    phone: '5511987651212',
    email: 'ana.souza@email.com',
    notes: null,
    birthDate: null,
    referral: 'Instagram',
    optIn: true,
    visits: 7,
    lastDaysAgo: 82,
    everyDays: 35,
    services: ['manutencao', 'alongamento'],
  },
  {
    id: 'renata-gomes',
    name: 'Renata Gomes',
    phone: '5511987651313',
    email: null,
    notes: null,
    birthDate: '1979-12-01',
    referral: 'Indicação',
    optIn: true,
    visits: 9,
    lastDaysAgo: 98,
    everyDays: 30,
    services: ['manutencao', 'pedicure'],
  },
  {
    id: 'carla-dias',
    name: 'Carla Dias',
    phone: '5511987651414',
    email: 'carla.dias@email.com',
    notes: 'Prefere sábados.',
    birthDate: null,
    referral: 'Google',
    optIn: true,
    visits: 11,
    lastDaysAgo: 107,
    everyDays: 28,
    services: ['alongamento', 'manutencao', 'manutencao'],
  },
];

function toClientRow(c: DemoClient, today: IsoDate): ClientRow {
  // A margem cobre o domingo, que empurra o primeiro atendimento um dia para trás.
  const since = c.visits ? c.lastDaysAgo + (c.visits - 1) * c.everyDays + 3 : (c.since ?? 0);
  return {
    id: c.id,
    name: c.name,
    phone: c.phone,
    email: c.email,
    notes: c.notes,
    created_at: `${addDays(today, -since)}T12:00:00Z`,
    birth_date: c.birthDate,
    referral: c.referral,
    whatsapp_opt_in: c.optIn,
  };
}

function clientHistory(c: DemoClient, index: number, today: IsoDate): AppointmentRow[] {
  return Array.from({ length: c.visits }, (_, i) => {
    let date = addDays(today, -(c.lastDaysAgo + i * c.everyDays));
    if (weekdayOf(date) === 'sun') date = addDays(date, -1);
    const service = c.services[i % c.services.length]!;
    return {
      id: 100_000 + index * 100 + i,
      tenant_slug: usuarioExemplo.tenantSlug,
      date,
      start_time: i % 2 === 0 ? '14:00' : '10:00',
      duration_min: DURATION[service] ?? 60,
      service_ids: JSON.stringify([service]),
      client_name: c.name,
      client_phone: c.phone,
      notes: null,
      status: c.cancelled?.includes(i) ? 'cancelled' : 'done',
      origin: i % 3 === 0 ? 'site' : 'panel',
      created_at: `${date}T08:00:00Z`,
      updated_at: `${date}T08:00:00Z`,
    };
  });
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
