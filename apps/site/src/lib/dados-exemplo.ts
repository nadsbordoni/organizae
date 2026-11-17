import type { AstroCookies } from 'astro';
import { addDays, dayNumber, nowInBusinessTime, weekdayOf } from './agenda';
import { DEMO_CATEGORIES, demoFinanceStart, demoFinancialEntries } from './demo-finance';
import type { AppointmentStatus } from './dashboard-status';
import type { AgendaException, IsoDate } from '@/types/agenda';
import type {
  AgendaNotification,
  AppointmentRow,
  AuthenticatedUser,
  ClientRow,
  FinancialCategoryRow,
  FinancialEntryRow,
  ProfessionalRow,
  TimeOffRow,
} from '@/types/painel';

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

/** Horários que caíram, por mês: sem isso, um mês do exemplo seria igual ao outro nos relatórios. */
const FOLGA_DO_MES = [1, 2, 0, 1, 3, 0, 2, 1, 0, 2, 1, 3];

function caiu(date: IsoDate, indice: number): boolean {
  let hash = 0;
  for (const char of `${date}${indice}`) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % 10 < FOLGA_DO_MES[Number(date.slice(5, 7)) - 1]!;
}

function statusDe(indice: number, quando: 'passado' | 'hoje' | 'futuro', date: IsoDate, hoje: IsoDate): AppointmentStatus {
  if (quando === 'passado') {
    if (indice === 2) return 'cancelled';
    // Só antes da última semana: a semana que aparece na Agenda continua como estava.
    return dayNumber(hoje) - dayNumber(date) > 7 && caiu(date, indice) ? 'cancelled' : 'done';
  }
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
    status: i === cancelado ? 'cancelled' : statusDe(i, quando, date, hoje),
    origin: i % 2 === 0 ? ('site' as const) : ('panel' as const),
    created_at: `${date}T08:00:00Z`,
    updated_at: `${date}T08:00:00Z`,
  }));
}

/** Cenário da equipe na demonstração: só a dona atende, ou a dona com mais gente. */
export interface DemoOptions {
  team?: boolean;
}

export function forTenant(_tenantSlug: string, demo: DemoOptions = {}) {
  const hoje = nowInBusinessTime('America/Sao_Paulo').date;
  const team = demo.team ? TEAM : TEAM.filter((p) => p.role === 'owner');
  const between = (from: IsoDate, to: IsoDate) => {
    const rows: AppointmentRow[] = [];
    for (let d = from; d <= to; d = addDays(d, 1)) rows.push(...doDia(d, hoje));
    return rows;
  };

  return {
    async appointmentsOn(date: IsoDate): Promise<AppointmentRow[]> {
      return doDia(date, hoje);
    },

    async appointmentsBetween(from: IsoDate, to: IsoDate): Promise<AppointmentRow[]> {
      return between(from, to);
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

    async financialCategories(): Promise<FinancialCategoryRow[]> {
      return DEMO_CATEGORIES;
    },

    /** Com a API, `GET /financial-entries` no período pedido. */
    async financialEntries(): Promise<FinancialEntryRow[]> {
      return demoFinancialEntries(hoje, between(demoFinanceStart(hoje), addDays(hoje, 21)));
    },

    async professionals(): Promise<ProfessionalRow[]> {
      return team;
    },

    async professional(id: string): Promise<ProfessionalRow | undefined> {
      return team.find((p) => p.id === id);
    },

    /** Com a API, os bloqueios de dia inteiro de `GET /appointments`. */
    async timeOff(): Promise<TimeOffRow[]> {
      return TIME_OFF.filter((t) => team.some((p) => p.id === t.professional_id)).map((t) => ({
        id: t.id,
        professional_id: t.professional_id,
        starts_on: addDays(hoje, t.from),
        ends_on: addDays(hoje, t.to),
        reason: t.reason,
      }));
    },
  };
}

const DEMO_TEAM_COOKIE = 'organizae-demo-equipe';

/**
 * PROTÓTIPO: o cenário escolhido na tela de Equipe (`?demo=equipe` ou `?demo=solo`) fica num cookie
 * para valer também em Serviços. Sai com a API, quando a equipe vier do banco.
 */
export function demoOptions(url: URL, cookies: AstroCookies): DemoOptions {
  const choice = url.searchParams.get('demo');
  if (choice === 'equipe' || choice === 'solo') {
    cookies.set(DEMO_TEAM_COOKIE, choice, { path: '/painel', sameSite: 'lax', httpOnly: true });
    return { team: choice === 'equipe' };
  }
  return { team: cookies.get(DEMO_TEAM_COOKIE)?.value !== 'solo' };
}

/** Ausências de DEMONSTRAÇÃO, em dias a partir de hoje: uma férias agora, uma marcada e uma folga da dona. */
const TIME_OFF = [
  { id: 'ferias-larissa', professional_id: 'larissa-alves', from: -3, to: 6, reason: 'Férias' },
  { id: 'ferias-bianca', professional_id: 'bianca-reis', from: 35, to: 49, reason: 'Férias' },
  { id: 'folga-joana', professional_id: 'joana', from: 16, to: 16, reason: 'Folga' },
];

/** Equipe de DEMONSTRAÇÃO. A dona também atende; no cenário "só a dona", só ela aparece. */
const TEAM: ProfessionalRow[] = [
  {
    id: 'joana',
    name: usuarioExemplo.name!,
    phone: '5511988887777',
    description: 'Alongamento e manutenção',
    is_active: true,
    service_ids: ['alongamento', 'manutencao', 'esmaltacao', 'pedicure'],
    email: usuarioExemplo.email,
    role: 'owner',
  },
  {
    id: 'larissa-alves',
    name: 'Larissa Alves',
    phone: '5511995678902',
    description: 'Esmaltação e manutenção',
    is_active: true,
    service_ids: ['manutencao', 'esmaltacao'],
    email: 'larissa@exemplo.com',
    role: 'professional',
  },
  {
    id: 'bianca-reis',
    name: 'Bianca Reis',
    phone: '5511996781234',
    description: 'Pés e spa',
    is_active: true,
    service_ids: ['pedicure', 'spa-dos-pes'],
    email: 'bianca@exemplo.com',
    role: 'professional',
  },
  {
    id: 'tatiane-moura',
    name: 'Tatiane Moura',
    phone: '5511997894561',
    description: 'Alongamento em gel',
    is_active: false,
    service_ids: ['alongamento'],
    email: 'tatiane@exemplo.com',
    role: 'professional',
  },
];

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
