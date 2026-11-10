import type { BookingContext } from './booking-ui';

/** JSON que `BookingPage.astro` embute em cada página do fluxo: páginas separadas não dividem memória. */
export function readContext(): BookingContext | undefined {
  const raw = document.getElementById('dados-agendamento')?.textContent;
  if (!raw) return undefined;

  return JSON.parse(raw) as BookingContext;
}
