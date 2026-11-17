/** Filtro em `<select data-autosubmit>` aplica ao trocar a opção. Sem JavaScript, vale o Enter na busca ou o botão do `<noscript>`. */
export function wireAutoSubmit() {
  for (const select of document.querySelectorAll<HTMLSelectElement>('select[data-autosubmit]')) {
    select.addEventListener('change', () => select.form?.requestSubmit());
  }
}
