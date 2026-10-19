/**
 * Agenda de um negócio: expediente, pausas e catálogo de serviços.
 *
 * Isto é DADO puro, como o resto de `SiteConfig`: quem configura descreve
 * "abro às 8, fecho às 19:30, almoço de 12 às 13, blindagem leva 1h" e o motor
 * de `lib/agenda.ts` calcula sozinho quais horários cabem. Não existe lista de
 * horários escrita à mão em lugar nenhum — ela seria impossível de manter
 * quando um serviço muda de duração.
 */

/** Dia da semana. `sun` = domingo, como `Date.prototype.getUTCDay()`. */
export type Weekday = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat';

/** Hora de parede do negócio, 24h, sempre com dois dígitos. Ex: '08:00'. */
export type ClockTime = string;

/** Data no calendário do negócio. Ex: '2026-09-14'. */
export type IsoDate = string;

/** Faixa de horas dentro de um dia. `to` é exclusivo. */
export interface TimeRange {
  from: ClockTime;
  to: ClockTime;
}

/**
 * Expediente de um dia.
 *
 * `breaks` é o que impede a cliente de marcar no almoço: o motor desconta cada
 * pausa do expediente antes de gerar horário nenhum, então não há como marcar
 * dentro dela nem "por cima" dela — um serviço de 2h não é oferecido às 11:00
 * se o almoço começa ao meio-dia.
 */
export interface DayHours {
  opens: ClockTime;
  closes: ClockTime;
  /** Pausas no meio do expediente: almoço, café, intervalo de limpeza. */
  breaks?: Array<TimeRange & { label?: string }>;
}

/**
 * Dia que não segue o padrão da semana: feriado, férias, ou expediente
 * diferente. Tem precedência sobre `Agenda.hours`.
 */
export interface AgendaException {
  date: IsoDate;
  /** `null` fecha o dia. Um `DayHours` substitui o expediente daquele dia. */
  hours: DayHours | null;
  /** Aparece na tela quando a cliente toca num dia fechado. Ex: 'Feriado'. */
  reason?: string;
}

export interface Service {
  /** Identificador estável, em kebab-case. Não mude depois de publicar. */
  id: string;
  name: string;
  /**
   * Duração TOTAL do atendimento, em minutos — é ela que define quais horários
   * aparecem. Inclua o tempo de preparo e de limpeza: o que é reservado na
   * agenda é este número, não o tempo "de mão na massa".
   */
  durationMinutes: number;
  /** Texto livre, como no resto do projeto. Ex: 'R$ 90,00'. Omitido, não aparece. */
  price?: string;
  description?: string;
  /** Anunciado, mas ainda não agendável. Aparece esmaecido, sem seleção. */
  soon?: boolean;
  /** Tira do ar sem apagar a configuração. */
  hidden?: boolean;
}

export interface ServiceCategory {
  /** Identificador estável, em kebab-case. */
  id: string;
  name: string;
  /** Uma linha com os serviços da categoria, para a cliente escolher o grupo. */
  description?: string;
  image?: { src: string; alt: string };
  services: Service[];
  hidden?: boolean;
}

/**
 * Por onde o pedido de horário chega até o negócio.
 *
 * ⚠️ HOJE SÓ EXISTE `whatsapp`: o site calcula o horário livre, mas nada é
 * RESERVADO. Por isso o passo final diz "pedido enviado", e não "agendamento
 * confirmado". A API ainda não está ligada ao fluxo público; quando
 * estiver, entra `via: 'server'` e o motor
 * recebe `SlotQuery.busy`, que hoje chega sempre vazio.
 */
export interface BookingRequest {
  via: 'whatsapp';
  /** Só dígitos, com DDI e DDD. Ex: '5511999998888'. */
  phone: string;
}

export interface Agenda {
  /**
   * Fuso do negócio, IANA. Ex: 'America/Sao_Paulo'.
   *
   * Não é detalhe: sem ele, quem abre o link viajando veria "hoje" e "agora" do
   * próprio celular, e a antecedência mínima sairia errada.
   */
  timezone: string;

  /**
   * Expediente por dia da semana. Dia AUSENTE = fechado — é o que faz a
   * configuração listar só os dias em que se trabalha.
   */
  hours: Partial<Record<Weekday, DayHours>>;

  /** Feriados, férias e dias de expediente diferente. */
  exceptions?: AgendaException[];

  categories: ServiceCategory[];

  /**
   * De quanto em quanto tempo um atendimento pode COMEÇAR. Padrão 30.
   *
   * Não é a duração do serviço: com grade de 30 e serviço de 2h, os começos
   * possíveis são 08:00, 08:30, 09:00… e cada um reserva 2h.
   */
  slotStepMinutes?: number;

  /**
   * Antecedência mínima, em horas. Padrão 12. Impede o "marquei para daqui a
   * 10 minutos" que ninguém vê em tempo.
   */
  minNoticeHours?: number;

  /** Quantos dias à frente é possível marcar. Padrão 60. */
  horizonDays?: number;

  request: BookingRequest;

  /** Regras que a cliente precisa saber: tolerância, cancelamento, sinal. */
  policies?: string[];

  /**
   * Frase abaixo do formulário de revisão, sobre o uso dos dados. Um padrão é
   * aplicado quando omitida.
   */
  privacyNote?: string;
}
