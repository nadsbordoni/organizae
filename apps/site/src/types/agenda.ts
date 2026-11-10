/**
 * Agenda de um negócio. Só DADO: `lib/agenda.ts` calcula quais horários cabem. Não há
 * lista de horários à mão: seria impossível de manter quando um serviço muda de duração.
 */

/** `sun` = domingo, como `Date.prototype.getUTCDay()`. */
export type Weekday = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat';

/** Hora de parede do negócio, 24h, sempre com dois dígitos. Ex: '08:00'. */
export type ClockTime = string;

/** Data no calendário do negócio. Ex: '2026-09-14'. */
export type IsoDate = string;

/** `to` é exclusivo. */
export interface TimeRange {
  from: ClockTime;
  to: ClockTime;
}

export interface DayHours {
  opens: ClockTime;
  closes: ClockTime;
  /**
   * Almoço, café, limpeza. O motor desconta antes de gerar horário: nenhum serviço é
   * oferecido dentro nem "por cima" de uma pausa.
   */
  breaks?: Array<TimeRange & { label?: string }>;
}

/** Feriado, férias ou expediente diferente. Tem precedência sobre `Agenda.hours`. */
export interface AgendaException {
  date: IsoDate;
  /** `null` fecha o dia. */
  hours: DayHours | null;
  /** Aparece quando a cliente toca no dia fechado. Ex: 'Feriado'. */
  reason?: string;
}

export interface Service {
  /** Estável, em kebab-case. NÃO mude depois de publicar. */
  id: string;
  name: string;
  /** TOTAL reservado na agenda: inclua preparo e limpeza, não só o tempo "de mão na massa". */
  durationMinutes: number;
  /** Texto livre. Ex: 'R$ 90,00'. */
  price?: string;
  description?: string;
  /** Anunciado, mas ainda não agendável. Aparece esmaecido, sem seleção. */
  soon?: boolean;
  hidden?: boolean;
}

export interface ServiceCategory {
  /** Estável, em kebab-case. */
  id: string;
  name: string;
  /** Uma linha com os serviços da categoria. */
  description?: string;
  image?: { src: string; alt: string };
  services: Service[];
  hidden?: boolean;
}

/**
 * HOJE SÓ EXISTE `whatsapp`: nada é RESERVADO, por isso o passo final diz "pedido
 * enviado", e não "agendamento confirmado". Até existir `via: 'server'`, `SlotQuery.busy` chega vazio.
 */
export interface BookingRequest {
  via: 'whatsapp';
  /** Só dígitos, com DDI e DDD. Ex: '5511999998888'. */
  phone: string;
}

export interface Agenda {
  /**
   * IANA. Ex: 'America/Sao_Paulo'. Sem ele, quem abre o link viajando veria "hoje" e
   * "agora" do próprio celular, e a antecedência mínima sairia errada.
   */
  timezone: string;

  /** Dia AUSENTE = fechado. */
  hours: Partial<Record<Weekday, DayHours>>;

  exceptions?: AgendaException[];

  categories: ServiceCategory[];

  /** De quanto em quanto tempo um atendimento pode COMEÇAR (não é a duração). Padrão 30. */
  slotStepMinutes?: number;

  /** Antecedência mínima, em horas. Padrão 12. */
  minNoticeHours?: number;

  /** Quantos dias à frente é possível marcar. Padrão 60. */
  horizonDays?: number;

  request: BookingRequest;

  /** Ex: tolerância, cancelamento, sinal. */
  policies?: string[];

  /** Uso dos dados, abaixo do formulário de revisão. Omitida, vale um padrão. */
  privacyNote?: string;
}
