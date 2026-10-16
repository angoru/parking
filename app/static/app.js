// Pequeños comportamientos de la interfaz. Van en un fichero propio (y no en atributos
// onclick/onchange) para que la política de seguridad (CSP) pueda bloquear todo script en línea.

// Envía el formulario al cambiar el campo (selector de fecha del tablero)
document.addEventListener("change", (e) => {
  if (e.target.matches("[data-autoenvio]")) e.target.form.submit();
});

// Marca en azul el titular de una plaza fija mientras se escribe
document.addEventListener("input", (e) => {
  if (e.target.matches("[data-titular]")) {
    e.target.classList.toggle("fija", e.target.value.trim() !== "");
  }
});

// Desactiva los botones al enviar un formulario, para que un doble toque no lo envíe dos veces.
// Se hace después del envío para que el botón pulsado siga viajando con el formulario.
document.addEventListener("submit", (e) => {
  if (e.defaultPrevented || e.target.method !== "post") return;
  const botones = e.target.querySelectorAll("button");
  setTimeout(() => botones.forEach((b) => { b.disabled = true; }), 0);
});

// Al volver atrás, el navegador puede mostrar la página con los botones desactivados
window.addEventListener("pageshow", () => {
  document.querySelectorAll("button:disabled").forEach((b) => { b.disabled = false; });
});

// Pide confirmación antes de acciones que no se pueden deshacer
document.addEventListener("click", (e) => {
  const boton = e.target.closest("[data-confirmar]");
  if (boton && !window.confirm(boton.dataset.confirmar)) e.preventDefault();
});
