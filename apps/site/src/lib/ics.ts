import type { ClockTime, IsoDate } from '@/types/agenda';

/**
 * .ics gerado no navegador. HORA FLUTUANTE de propósito (`DTSTART:20260914T140000`, sem `Z` nem `TZID`):
 * pelo RFC 5545 vale o fuso de quem abre, o certo com cliente e negócio na mesma cidade. Converter
 * para UTC exigiria a regra de horário de verão dentro do arquivo, e erra por uma hora se feita à mão.
 */

export interface CalendarEvent {
  /** Mesmo pedido, mesmo UID: baixar de novo atualiza o evento em vez de duplicar. */
  uid: string;
  title: string;
  date: IsoDate;
  start: ClockTime;
  durationMinutes: number;
  description?: string;
  location?: string;
}

export function buildIcs(event: CalendarEvent): string {
  const start = stamp(event.date, event.start);
  const end = stamp(...addMinutes(event.date, event.start, event.durationMinutes));

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//bio-agenda//PT-BR',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:${event.uid}`,
    `DTSTAMP:${utcStamp(new Date())}`,
    `DTSTART:${start}`,
    `DTEND:${end}`,
    `SUMMARY:${escapeText(event.title)}`,
    ...(event.description ? [`DESCRIPTION:${escapeText(event.description)}`] : []),
    ...(event.location ? [`LOCATION:${escapeText(event.location)}`] : []),
    // Lembrete 2h antes: dá tempo de se organizar, sem avisar tão cedo que a pessoa esqueça de novo.
    'BEGIN:VALARM',
    'ACTION:DISPLAY',
    'DESCRIPTION:Lembrete do seu horário',
    'TRIGGER:-PT2H',
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ];

  // CRLF em TODA linha, inclusive a última: alguns aplicativos recusam \n ou arquivo sem o fecho.
  return `${lines.flatMap(fold).join('\r\n')}\r\n`;
}

/** 'YYYY-MM-DD' + 'HH:MM' → '20260914T140000'. */
function stamp(date: IsoDate, time: ClockTime): string {
  return `${date.replace(/-/g, '')}T${time.replace(':', '')}00`;
}

/** Já vira o dia quando a soma passa da meia-noite. */
function addMinutes(date: IsoDate, time: ClockTime, minutes: number): [IsoDate, ClockTime] {
  const [hour, minute] = time.split(':').map(Number);
  const at = new Date(`${date}T00:00:00Z`);
  at.setUTCMinutes(at.getUTCMinutes() + hour * 60 + minute + minutes);

  const iso = at.toISOString();
  return [iso.slice(0, 10), iso.slice(11, 16)];
}

function utcStamp(at: Date): string {
  return `${at.toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`;
}

/** Vírgula, ponto e vírgula e quebra de linha são separadores no formato. */
function escapeText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r\n|\r|\n/g, '\\n');
}

/** Dobra em 75 OCTETOS, como o formato exige. Conta bytes: cortar "ç" no meio corrompe o arquivo. */
function fold(line: string): string[] {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return [line];

  const parts: string[] = [];
  let current = '';
  let size = 0;

  for (const char of line) {
    const charSize = new TextEncoder().encode(char).length;
    // 74 na continuação: o espaço inicial também conta para o limite.
    if (size + charSize > (parts.length ? 74 : 75)) {
      parts.push(current);
      current = '';
      size = 0;
    }
    current += char;
    size += charSize;
  }
  parts.push(current);

  return parts.map((part, index) => (index ? ` ${part}` : part));
}
