import { foldText, numericDate } from './painel';
import type { PanelTone } from './painel';
import type { IconName } from '@/types/blocks';
import type { IsoDate } from '@/types/agenda';
import type { ProfessionalRow, TimeOffRow } from '@/types/painel';

export type AgendaState = 'open' | 'away' | 'closed';

export interface TeamAgenda {
  state: AgendaState;
  badge: { label: string; tone: PanelTone; icon: IconName };
  /** Próxima ausência marcada, depois de hoje. */
  next?: TimeOffRow;
}

/** Se a agenda da pessoa recebe agendamentos hoje. Sem gênero de propósito, como as situações dos clientes. */
export function teamAgenda(professional: ProfessionalRow, timeOff: TimeOffRow[], today: IsoDate): TeamAgenda {
  const own = timeOff
    .filter((t) => t.professional_id === professional.id && t.ends_on >= today)
    .sort((a, b) => a.starts_on.localeCompare(b.starts_on));
  const now = own.find((t) => t.starts_on <= today);
  const next = own.find((t) => t.starts_on > today);

  if (!professional.is_active) {
    return { state: 'closed', badge: { label: 'Agenda fechada', tone: 'danger', icon: 'close' }, next };
  }
  if (now) {
    const until = now.ends_on === today ? 'hoje' : `até ${numericDate(now.ends_on, false)}`;
    return { state: 'away', badge: { label: `${now.reason} ${until}`, tone: 'attention', icon: 'clock' }, next };
  }
  return { state: 'open', badge: { label: 'Atendendo', tone: 'positive', icon: 'check-circle' }, next };
}

/** 'Férias de 15/12 a 29/12', ou 'Folga em 26/11' quando é um dia só. */
export function timeOffLabel(t: TimeOffRow): string {
  return t.starts_on === t.ends_on
    ? `${t.reason} em ${numericDate(t.starts_on, false)}`
    : `${t.reason} de ${numericDate(t.starts_on, false)} a ${numericDate(t.ends_on, false)}`;
}

export const roleLabel = (professional: ProfessionalRow) =>
  professional.role === 'owner' ? 'Administração' : 'Profissional';

/** Nome ou especialidade sem acento nem caixa; telefone a partir de 3 dígitos. */
export function matchesProfessional(professional: ProfessionalRow, query: string): boolean {
  const term = foldText(query);
  if (!term) return true;
  const digits = query.replace(/\D/g, '');
  return (
    foldText(`${professional.name} ${professional.description ?? ''}`).includes(term) ||
    (digits.length >= 3 && Boolean(professional.phone?.includes(digits)))
  );
}
