/** Planilha para o Excel em português: `;` separa as colunas e o BOM faz os acentos abrirem certos. */
export function toCsv(lines: string[][]): string {
  // Célula que começa com = + - @ vira fórmula no Excel; o apóstrofo a mantém como texto.
  const cell = (value: string) => `"${value.replace(/^[=+\-@\t\r]/, "'$&").replace(/"/g, '""')}"`;
  return `\uFEFF${lines.map((line) => line.map(cell).join(';')).join('\r\n')}`;
}

/** Link `data:` para baixar a planilha direto, sem passar pelo servidor. */
export const csvHref = (lines: string[][]) => `data:text/csv;charset=utf-8,${encodeURIComponent(toCsv(lines))}`;
