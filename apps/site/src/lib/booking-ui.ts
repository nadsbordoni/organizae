import {
  AGENDA_DEFAULTS,
  WEEKDAYS,
  addDays,
  firstAvailableDate,
  formatDuration,
  formatLongDate,
  formatMonth,
  formatShortDate,
  hasSlots,
  nowInBusinessTime,
  slotsFor,
  toClock,
  toIsoDate,
  toMinutes,
  totalPrice,
  weekdayOf,
} from './agenda';
import {
  readNotes,
  readSelection,
  selectionMinutes,
  stepHref,
  writeNotes,
  type Selection,
} from './booking-state';
import { buildIcs } from './ics';
import { whatsappUrl } from './links';
import type { Agenda, IsoDate, Service } from '@/types/agenda';

/**
 * Os passos do agendamento no navegador.
 *
 * Uma função por página. Cada uma monta só o seu passo, e o que já foi
 * escolhido chega pela URL — não há estado compartilhado entre elas, porque
 * entre um passo e outro o navegador realmente troca de página.
 *
 * As quatro moram no mesmo módulo de propósito: o bundler produz UM arquivo
 * compartilhado, então navegar de um passo ao outro não baixa JavaScript de
 * novo. O custo é alguns KB a mais no primeiro passo.
 *
 * O CONTRATO com os componentes são os atributos `data-*` lidos aqui. Os nomes
 * de classe das peças criadas em runtime (`calendar__day`, `slots__chip`) estão
 * estilizados com `:global()` em `Calendar.astro` e `SlotPicker.astro`.
 */

export interface BookingContext {
  agenda: Agenda;
  business: {
    name: string;
    /** Raiz das rotas do fluxo. Ex: '/exemplo/agendar'. */
    base: string;
    homeHref: string;
    /** Entra no `.ics` como local do compromisso. */
    address?: string;
  };
}

/** Nome do grupo de caixas do passo de serviços. Lido aqui, escrito no Astro. */
export const SERVICE_FIELD_NAME = 'servicos';

/* --- Passo 1: serviços ------------------------------------------------------ */

export function mountServices(root: HTMLElement, { agenda, business }: BookingContext): void {
  const now = nowInBusinessTime(agenda.timezone);
  const catalog = agenda.categories.flatMap((category) => category.services);

  const checkboxes = [
    ...root.querySelectorAll<HTMLInputElement>(`input[name="${SERVICE_FIELD_NAME}"]`),
  ];
  const tally = must<HTMLElement>(root, '[data-tally]');
  const tallyCount = must<HTMLElement>(root, '[data-tally-count]');
  const tallyTotals = must<HTMLElement>(root, '[data-tally-totals]');
  const next = must<HTMLAnchorElement>(root, '[data-next]');

  // Quem volta do passo 2 chega com a escolha na URL: as caixas voltam marcadas
  // em vez de a pessoa refazer tudo.
  const fromUrl = readSelection(agenda, window.location.search, now);
  for (const box of checkboxes) {
    box.checked = fromUrl.services.some((service) => service.id === box.value);
  }

  function sync(): void {
    const chosen = new Set(checkboxes.filter((box) => box.checked).map((box) => box.value));
    const services = catalog.filter((service) => chosen.has(service.id));
    const count = services.length;

    tally.hidden = count === 0;
    if (count) {
      tallyCount.textContent = `${count} ${count === 1 ? 'serviço' : 'serviços'}`;
      tallyTotals.textContent = [
        formatDuration(selectionMinutes({ services })),
        totalPrice(services),
      ]
        .filter(Boolean)
        .join(' · ');
    }

    for (const category of agenda.categories) {
      const badge = root.querySelector<HTMLElement>(`[data-category-count="${category.id}"]`);
      if (!badge) continue;
      const inside = services.filter((service) =>
        category.services.some((item) => item.id === service.id),
      ).length;
      // Vazio some pelo CSS — categoria sem escolha não ganha selo.
      badge.textContent = inside ? String(inside) : '';
    }

    // O botão é um link de verdade, e o endereço carrega a escolha. Sem nada
    // marcado ele fica desligado em vez de levar a um passo 2 sem conteúdo.
    next.href = stepHref(business.base, 'data', { services });
    setEnabled(next, count > 0);
  }

  // `aria-disabled` avisa o leitor de tela, mas NÃO impede o clique: âncora não
  // conhece `disabled`. Sem isto, clicar com nada marcado ia ao passo 2, que
  // devolvia para cá na hora — um pisca-pisca sem explicação. Mesmo guarda que o
  // botão de enviar já tinha.
  next.addEventListener('click', (event) => {
    if (isDisabled(next)) event.preventDefault();
  });

  for (const box of checkboxes) box.addEventListener('change', sync);
  sync();
}

/* --- Passo 2: data e horário ------------------------------------------------ */

export function mountSchedule(root: HTMLElement, { agenda, business }: BookingContext): void {
  const now = nowInBusinessTime(agenda.timezone);
  const selection = readSelection(agenda, window.location.search, now);

  // Chegou sem serviço: link velho, URL editada, ou volta do navegador depois de
  // desmarcar tudo. Volta ao começo em vez de mostrar um calendário sem sentido.
  if (!selection.services.length) {
    window.location.replace(business.base);
    return;
  }

  const lastDate = addDays(now.date, agenda.horizonDays ?? AGENDA_DEFAULTS.horizonDays);
  const minutes = selectionMinutes(selection);
  const service = { durationMinutes: minutes };

  const monthLabel = must<HTMLElement>(root, '[data-month-label]');
  const grid = must<HTMLElement>(root, '[data-calendar-grid]');
  const slotsRegion = must<HTMLElement>(root, '[data-slots-region]');
  const slotsGrid = must<HTMLElement>(root, '[data-slots-grid]');
  const slotsDay = must<HTMLElement>(root, '[data-slots-day]');
  const slotsEmpty = must<HTMLElement>(root, '[data-slots-empty]');
  const slotsNoFit = must<HTMLElement>(root, '[data-slots-nofit]');
  const next = must<HTMLAnchorElement>(root, '[data-next]');

  // O voltar sai do build sem query; aqui ganha a escolha, para o passo 1 reabrir
  // com as caixas marcadas.
  must<HTMLAnchorElement>(document, '[data-back]').href = stepHref(business.base, '', {
    services: selection.services,
  });

  must<HTMLElement>(root, '[data-duration-note]').textContent =
    `${listNames(selection.services)} — ${formatDuration(minutes)} no total.`;

  // Abre já no primeiro dia com vaga, em vez de num mês vazio que a pessoa
  // teria de vasculhar. Somando serviços, esse dia pode estar semanas à frente —
  // e é exatamente o que ela precisa saber de cara.
  let date = selection.date ?? firstAvailableDate({ agenda, service, now });
  let time = selection.time;
  let view = date
    ? { year: year(date), month: month(date) }
    : { year: year(now.date), month: month(now.date) };

  for (const button of root.querySelectorAll<HTMLButtonElement>('[data-month-step]')) {
    button.addEventListener('click', () => {
      // Soma em "meses absolutos" para dezembro → janeiro virar o ano sozinho.
      const absolute = view.year * 12 + (view.month - 1) + Number(button.dataset.monthStep);
      view = { year: Math.floor(absolute / 12), month: (absolute % 12) + 1 };
      renderCalendar();
      // No limite do horizonte a seta se desliga com o foco nela, e ele cairia no body.
      if (button.disabled) {
        must<HTMLButtonElement>(root, `[data-month-step="${-Number(button.dataset.monthStep)}"]`).focus();
      }
    });
  }

  function renderCalendar(): void {
    monthLabel.textContent = formatMonth(view.year, view.month);

    must<HTMLButtonElement>(root, '[data-month-step="-1"]').disabled =
      toIsoDate(view.year, view.month, 1) <= firstOfMonth(now.date);
    must<HTMLButtonElement>(root, '[data-month-step="1"]').disabled =
      toIsoDate(view.year, view.month, 1) >= firstOfMonth(lastDate);

    grid.replaceChildren();

    // Espaços até o dia 1 cair na coluna certa. A semana começa no domingo,
    // como o cabeçalho D S T Q Q S S.
    const offset = WEEKDAYS.indexOf(weekdayOf(toIsoDate(view.year, view.month, 1)));
    for (let i = 0; i < offset; i += 1) {
      const blank = document.createElement('span');
      blank.className = 'calendar__blank';
      grid.append(blank);
    }

    // Dia 0 do mês seguinte é o último deste — vale para fevereiro bissexto.
    const total = new Date(Date.UTC(view.year, view.month, 0)).getUTCDate();

    for (let day = 1; day <= total; day += 1) {
      const cellDate = toIsoDate(view.year, view.month, day);
      const free = hasSlots({ agenda, service, date: cellDate, now });

      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'calendar__day';
      cell.textContent = String(day);
      cell.disabled = !free;

      if (free) cell.dataset.free = '';
      if (cellDate === now.date) cell.dataset.today = '';
      cell.setAttribute('aria-pressed', String(cellDate === date));
      // O número sozinho não diz nada fora da grade visual; o rótulo diz a data
      // inteira e se dá para escolher.
      cell.setAttribute('aria-label', `${formatLongDate(cellDate)}${free ? '' : ' — sem horário'}`);

      cell.addEventListener('click', () => {
        date = cellDate;
        time = undefined;
        view = { year: year(cellDate), month: month(cellDate) };
        renderCalendar();
        // A grade foi recriada: sem isto o foco vai para o body e o leitor de tela
        // perde a posição.
        grid.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus();
        renderSlots();
        syncNext();
      });

      grid.append(cell);
    }
  }

  function renderSlots(): void {
    slotsGrid.replaceChildren();
    slotsRegion.hidden = false;

    // Sem `date` é porque nenhum dia do horizonte comporta a soma dos serviços.
    // Sem este aviso a tela ficava muda, com o calendário todo apagado.
    slotsNoFit.hidden = Boolean(date);
    if (!date) {
      slotsDay.textContent = '';
      slotsEmpty.hidden = true;
      return;
    }

    slotsDay.textContent = formatShortDate(date);

    const times = slotsFor({ agenda, service, date, now });
    slotsEmpty.hidden = times.length > 0;

    for (const slot of times) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'slots__chip';
      chip.textContent = slot;
      chip.setAttribute('aria-pressed', String(slot === time));
      // O fim do atendimento é o que a pessoa precisa para planejar o dia, e ele
      // muda conforme os serviços escolhidos.
      chip.setAttribute('aria-label', `${slot} às ${toClock(toMinutes(slot) + minutes)}`);

      chip.addEventListener('click', () => {
        time = slot;
        for (const other of slotsGrid.children) {
          other.setAttribute('aria-pressed', String(other === chip));
        }
        syncNext();
      });

      slotsGrid.append(chip);
    }
  }

  function syncNext(): void {
    const ready = Boolean(date && time);
    next.href = stepHref(business.base, 'revisao', { ...selection, date, time });
    setEnabled(next, ready);
  }

  // Mesma guarda do passo 1: sem dia e hora escolhidos, o clique não navega.
  next.addEventListener('click', (event) => {
    if (isDisabled(next)) event.preventDefault();
  });

  renderCalendar();
  renderSlots();
  syncNext();
}

/* --- Passo 3: revisão ------------------------------------------------------- */

export function mountReview(root: HTMLElement, { agenda, business }: BookingContext): void {
  const now = nowInBusinessTime(agenda.timezone);
  const selection = readSelection(agenda, window.location.search, now);

  // Sem serviço, dia ou hora válidos não há o que revisar. `readSelection` já
  // derruba data vencida e horário que não é mais oferecido; com os serviços de
  // pé, volta ao passo 2 para escolher outro horário.
  if (!selection.services.length || !selection.date || !selection.time) {
    window.location.replace(
      stepHref(business.base, selection.services.length ? 'data' : '', selection),
    );
    return;
  }

  const linesEmpty = must<HTMLElement>(root, '[data-lines-empty]');
  const totals = must<HTMLElement>(root, '[data-totals]');
  const totalDurationOut = must<HTMLElement>(root, '[data-total-duration]');
  const totalPriceOut = must<HTMLElement>(root, '[data-total-price]');
  const notes = must<HTMLTextAreaElement>(root, '[data-notes]');
  const submit = must<HTMLAnchorElement>(root, '[data-submit]');
  const back = must<HTMLAnchorElement>(document, '[data-back]');

  let chosen = [...selection.services];

  notes.value = readNotes();
  notes.addEventListener('input', () => writeNotes(notes.value.trim()));

  must<HTMLElement>(root, '[data-detail="data"]').textContent = formatLongDate(selection.date);

  for (const button of root.querySelectorAll<HTMLButtonElement>('[data-remove-service]')) {
    button.addEventListener('click', () => {
      chosen = chosen.filter((service) => service.id !== button.dataset.removeService);
      // TIRAR é sempre seguro: se o conjunto maior cabia neste horário, o menor
      // também cabe — só termina mais cedo. Por isso não revalidamos a agenda,
      // só refazemos as somas. Acrescentar é que exigiria voltar ao passo 2.
      render();

      // A linha sumiu com o foco dentro: vai para o próximo "tirar", ou para o
      // aviso de lista vazia.
      const remaining = [
        ...root.querySelectorAll<HTMLButtonElement>('[data-remove-service]'),
      ].filter((other) => !other.closest('[hidden]'));
      const after = remaining.find(
        (other) => button.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
      (after ?? remaining[remaining.length - 1] ?? linesEmpty).focus();
    });
  }

  function render(): void {
    for (const category of agenda.categories) {
      for (const service of category.services) {
        const line = root.querySelector<HTMLElement>(`[data-service-line="${service.id}"]`);
        if (line) line.hidden = !chosen.some((item) => item.id === service.id);
      }
    }

    const empty = chosen.length === 0;
    linesEmpty.hidden = !empty;
    totals.hidden = empty;
    setEnabled(submit, !empty);

    const minutes = selectionMinutes({ services: chosen });
    const start = selection.time!;
    const end = toClock(toMinutes(start) + minutes);

    must<HTMLElement>(root, '[data-detail="horario"]').textContent = empty
      ? ''
      : `${start} às ${end}`;

    if (!empty) {
      totalDurationOut.textContent = formatDuration(minutes);
      // Vazio quando algum serviço não tem valor legível: a linha some pelo CSS,
      // em vez de anunciar um total menor do que a conta real.
      totalPriceOut.textContent = totalPrice(chosen) ?? '';
    }

    submit.href = stepHref(business.base, 'enviado', { ...selection, services: chosen });
    back.href = empty
      ? business.base
      : stepHref(business.base, 'data', { ...selection, services: chosen });
  }

  submit.addEventListener('click', (event) => {
    if (isDisabled(submit)) {
      event.preventDefault();
      return;
    }
    // A conversa abre AGORA, dentro do clique — é o que o navegador exige para
    // não tratar como pop-up. A navegação para a conclusão segue normalmente.
    window.open(
      whatsappUrl(agenda.request.phone, buildMessage(chosen, selection, notes.value)),
      '_blank',
      'noopener',
    );
  });

  render();
}

/* --- Conclusão --------------------------------------------------------------- */

export function mountSent(root: HTMLElement, { agenda, business }: BookingContext): void {
  const now = nowInBusinessTime(agenda.timezone);
  const selection = readSelection(agenda, window.location.search, now, {
    checkAvailability: false,
  });

  if (!selection.services.length || !selection.date || !selection.time) {
    window.location.replace(business.base);
    return;
  }

  const { services, date, time } = selection;
  // Lida uma vez e apagada: sem isto a observação reaparece em "Agendar outro horário".
  const notes = readNotes();
  writeNotes('');
  const minutes = selectionMinutes(selection);
  const end = toClock(toMinutes(time) + minutes);

  const values: Record<string, string> = {
    servicos: listNames(services),
    data: formatLongDate(date),
    horario: `${time} às ${end}`,
    duracao: formatDuration(minutes),
    preco: totalPrice(services) ?? '',
  };
  for (const [key, value] of Object.entries(values)) {
    const target = root.querySelector<HTMLElement>(`[data-detail="${key}"]`);
    if (target) target.textContent = value;
  }

  must<HTMLAnchorElement>(root, '[data-whatsapp]').href = whatsappUrl(
    agenda.request.phone,
    buildMessage(services, selection, notes),
  );

  const ids = services.map((service) => service.id).join('+');
  const ics = buildIcs({
    uid: `${date}T${time.replace(':', '')}-${ids}@${window.location.host}`,
    title: `${listNames(services)} — ${business.name}`,
    date,
    start: time,
    durationMinutes: minutes,
    description: `Agendamento solicitado pelo site.${
      totalPrice(services) ? ` Valor: ${totalPrice(services)}.` : ''
    }`,
    location: business.address,
  });

  const icsLink = must<HTMLAnchorElement>(root, '[data-ics]');
  icsLink.href = URL.createObjectURL(new Blob([ics], { type: 'text/calendar;charset=utf-8' }));
  icsLink.download = `agendamento-${date}.ics`;
}

/* --- Auxiliares -------------------------------------------------------------- */

function buildMessage(services: readonly Service[], selection: Selection, notes: string): string {
  const { date, time } = selection;
  if (!date || !time) return '';

  const minutes = selectionMinutes({ services: [...services] });

  // Emoji sai em `whatsappUrl()`: o WhatsApp não preenche a mensagem quando tem.
  const lines = [
    'Oi! Quero agendar um horário pelo site.',
    '',
    ...services.map(
      (service) =>
        `- ${service.name} (${formatDuration(service.durationMinutes)}${
          service.price ? `, ${service.price}` : ''
        })`,
    ),
    '',
    `Data: ${formatLongDate(date)}`,
    `Horário: ${time} às ${toClock(toMinutes(time) + minutes)}`,
    `Duração total: ${formatDuration(minutes)}`,
  ];

  const total = totalPrice(services);
  if (total) lines.push(`Valor total: ${total}`);

  const written = notes.trim();
  if (written) lines.push('', `Observações: ${written}`);

  return lines.join('\n');
}

/**
 * Liga e desliga um link que faz papel de botão. `aria-disabled` precisa valer
 * 'true': vazio conta como falso para o leitor de tela e para o CSS do estado.
 */
function setEnabled(link: HTMLAnchorElement, enabled: boolean): void {
  if (enabled) link.removeAttribute('aria-disabled');
  else link.setAttribute('aria-disabled', 'true');
  link.tabIndex = enabled ? 0 : -1;
}

function isDisabled(link: HTMLAnchorElement): boolean {
  return link.getAttribute('aria-disabled') === 'true';
}

function must<T extends Element>(root: ParentNode, selector: string): T {
  const found = root.querySelector<T>(selector);
  // Falha alto e cedo: um `data-*` renomeado num componente quebraria o passo em
  // silêncio, e o sintoma apareceria só num botão que não responde.
  if (!found) throw new Error(`Agendamento: falta o elemento ${selector}`);
  return found;
}

/** 'Blindagem', 'Blindagem e Design', 'Blindagem, Design e Pernas'. */
function listNames(services: readonly Service[]): string {
  const names = services.map((service) => service.name);
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} e ${names[names.length - 1]}`;
}

function year(date: IsoDate): number {
  return Number(date.slice(0, 4));
}

function month(date: IsoDate): number {
  return Number(date.slice(5, 7));
}

function firstOfMonth(date: IsoDate): IsoDate {
  return `${date.slice(0, 7)}-01`;
}
