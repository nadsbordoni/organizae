import type { BookingContext } from './booking-ui';

/**
 * O catálogo e o expediente que os passos leem no navegador.
 *
 * Cada página do fluxo embute o mesmo JSON (ver `BookingPage.astro`) porque,
 * sendo páginas separadas, não há estado em memória entre elas. São ~2,5 KB por
 * página, que comprimem bem e vêm no mesmo HTML — nenhuma requisição extra.
 */
export function readContext(): BookingContext | undefined {
  const raw = document.getElementById('dados-agendamento')?.textContent;
  if (!raw) return undefined;

  return JSON.parse(raw) as BookingContext;
}
