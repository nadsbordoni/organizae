/**
 * PROTÓTIPO, até a API existir: formulários `data-prototype` só validam e avançam, e guardam os
 * campos na sessão do navegador para o passo seguinte mostrar o que já foi digitado. NUNCA guarda
 * senha nem arquivo. Trocar pelo envio à API.
 */

const KEY = 'organizae:conta';

type Stored = Record<string, string | boolean>;
type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

export function readAccount(): Stored {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? '{}') as Stored;
  } catch {
    return {};
  }
}

function writeAccount(data: Stored) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(data));
  } catch {
    /* navegação privada antiga: o passo seguinte só não vem preenchido */
  }
}

const isSecret = (field: Field) => field.type === 'password' || field.type === 'file';
const isCheck = (field: Field): field is HTMLInputElement => field.type === 'checkbox';

export function wirePrototypeForms() {
  const stored = readAccount();

  for (const form of document.querySelectorAll<HTMLFormElement>('form[data-prototype]')) {
    const fields = [...form.elements].filter((el): el is Field => 'name' in el && Boolean((el as Field).name));

    for (const field of fields) {
      if (isSecret(field) || !(field.name in stored)) continue;
      if (isCheck(field)) field.checked = stored[field.name] === true;
      else field.value = String(stored[field.name]);
      // Quem desenha a partir do campo (horários, logo, serviços) atualiza junto.
      field.dispatchEvent(new Event('input', { bubbles: true }));
      field.dispatchEvent(new Event('change', { bubbles: true }));
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const data = readAccount();
      for (const field of fields) {
        if (isSecret(field)) continue;
        data[field.name] = isCheck(field) ? field.checked : field.value;
      }
      writeAccount(data);
      location.assign(form.getAttribute('action') ?? '/painel');
    });
  }

  // `data-lock-submit`: o botão só libera com o formulário válido.
  for (const form of document.querySelectorAll<HTMLFormElement>('form[data-lock-submit]')) {
    const submit = form.querySelector<HTMLButtonElement>('[type="submit"]');
    const sync = () => {
      if (submit) submit.disabled = !form.checkValidity();
    };
    form.addEventListener('input', sync);
    sync();
  }
}
