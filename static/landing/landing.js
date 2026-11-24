// Página de ParkOps: menú, animaciones, recorrido por la app y formulario de prueba gratis

// Sombra del menú al hacer scroll
const nav = document.getElementById("nav");
addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 10));
document.querySelectorAll("#mm a").forEach(a => a.addEventListener("click", () => document.getElementById("mm").classList.remove("open")));

// Aparición al hacer scroll
const io = new IntersectionObserver(es => es.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
}), { threshold: .12 });
document.querySelectorAll(".reveal").forEach(el => io.observe(el));

// Botón de un plan → preselecciona el plan en el formulario
document.querySelectorAll("[data-plan]").forEach(b => b.addEventListener("click", () => {
  const select = document.getElementById("f-plan");
  if (select) select.value = b.dataset.plan;
}));

// Formulario: se envía sin recargar; sin JS funciona como un formulario normal
(function () {
  const form = document.getElementById("signupForm");
  if (!form) return;
  const wa = document.getElementById("f-wa");
  const button = document.getElementById("signupBtn");
  const formError = document.getElementById("formError");
  const fields = { business_name: "f-biz", contact_name: "f-name", whatsapp: "f-wa" };

  wa.addEventListener("input", () => {
    const d = wa.value.replace(/\D/g, "").slice(0, 8);
    wa.value = d.length > 4 ? d.slice(0, 4) + " " + d.slice(4) : d;
  });

  function setError(name, message) {
    const field = document.getElementById(fields[name]).closest(".field");
    field.classList.toggle("err", !!message);
    if (message) field.querySelector(".msg").textContent = message;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError.hidden = true;

    // Validación rápida en el navegador; el servidor vuelve a validar
    const local = {
      business_name: document.getElementById("f-biz").value.trim().length > 1 ? "" : "Escribe el nombre de tu parqueo.",
      contact_name: document.getElementById("f-name").value.trim().length > 1 ? "" : "Escribe tu nombre.",
      whatsapp: wa.value.replace(/\D/g, "").length === 8 ? "" : "Escribe un número de 8 dígitos.",
    };
    Object.entries(local).forEach(([name, msg]) => setError(name, msg));
    if (Object.values(local).some(Boolean)) return;

    button.disabled = true;
    try {
      const response = await fetch(form.getAttribute("action"), {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      const data = await response.json();
      if (data.ok) {
        document.getElementById("doneBiz").textContent = data.business || document.getElementById("f-biz").value.trim();
        document.getElementById("formBody").style.display = "none";
        document.getElementById("formDone").style.display = "block";
        return;
      }
      Object.entries(data.errors || {}).forEach(([name, msg]) => fields[name] ? setError(name, msg) : null);
      if (data.error || (data.errors && data.errors.__all__)) {
        formError.textContent = data.error || data.errors.__all__;
        formError.hidden = false;
      }
    } catch (error) {
      formError.textContent = "No se pudo enviar. Revisa tu conexión e intenta de nuevo.";
      formError.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
})();

// Recorrido por la app
(function () {
  const MODS = [
    {v: "panel", nav: "panel", i: "bi-speedometer2", n: "Panel", d: "Al abrir la app ves lo que entró hoy, lo del mes y accesos directos a cada módulo."},
    {v: "placa", nav: "placa", i: "bi-search", n: "Buscador de placas", d: "Escribe parte de la placa y aparecen los carros que están adentro. Un toque y abres su salida."},
    {v: "ia", nav: "placa", i: "bi-camera", n: "Placa con IA", d: "Encuadra la placa, usa el zoom si estás lejos y la IA la escribe en el buscador."},
    {v: "entrada", nav: "placa", i: "bi-box-arrow-in-right", n: "Registrar entrada", d: "Se abre en una ventana sobre el buscador: la hora se pone sola, eliges la tarifa y listo."},
    {v: "ticket", nav: "placa", i: "bi-qr-code", n: "Ticket QR", d: "Imprime el ticket con su código QR. Al escanearlo, la placa aparece en el buscador."},
    {v: "salida", nav: "placa", i: "bi-cash-coin", n: "Salida y cobro", d: "El monto se calcula con tus tarifas. Cobras y sigues en el buscador, listo para el siguiente carro."},
    {v: "historial", nav: "historial", i: "bi-clock-history", n: "Historial", d: "Todos los vehículos del día, filtrados por activos o finalizados, con buscador por placa."},
    {v: "llaves", nav: "llaves", i: "bi-key", n: "Llaves en custodia", d: "Cada llave con su foto y número de gancho. Se borra sola cuando el carro sale."},
    {v: "mensual", nav: "panel", i: "bi-calendar-check", n: "Suscripciones", d: "Clientes mensuales, diarios o por hora con su propia tarifa. Al entrar, la app los reconoce."},
    {v: "reportes", nav: "panel", i: "bi-bar-chart-line", n: "Reportes", d: "Reporte del día, del mes o por placa, en PDF o Excel."},
  ];
  const DUR = 7000;
  const tour = document.getElementById("tour");
  if (!tour) return;
  const list = document.getElementById("tourList"), chips = document.getElementById("tourChips");
  MODS.forEach((m, k) => {
    list.insertAdjacentHTML("beforeend", `<button class="tmod" data-k="${k}"><span class="ti"><i class="bi ${m.i}"></i></span><span><b>${m.n}</b><p>${m.d}</p></span><span class="bar"></span></button>`);
    chips.insertAdjacentHTML("beforeend", `<button data-k="${k}"><i class="bi ${m.i}"></i>${m.n}</button>`);
  });
  tour.style.setProperty("--dur", DUR + "ms");
  let cur = -1, timer = null, timers = [], visible = false;
  const later = (fn, ms) => timers.push(setTimeout(fn, ms));
  const $ = (id) => document.getElementById(id);

  // QR de muestra del ticket
  (function () {
    const c = $("dQr").getContext("2d"), N = 25;
    c.fillStyle = "#fff"; c.fillRect(0, 0, N, N); c.fillStyle = "#111";
    let s = 7; const rnd = () => (s = (s * 9301 + 49297) % 233280) / 233280;
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (rnd() > .52) c.fillRect(x, y, 1, 1);
    [[0, 0], [N - 7, 0], [0, N - 7]].forEach(([x, y]) => {
      c.fillStyle = "#fff"; c.fillRect(Math.max(x - 1, 0), Math.max(y - 1, 0), 9, 9);
      c.fillStyle = "#111"; c.fillRect(x, y, 7, 7);
      c.fillStyle = "#fff"; c.fillRect(x + 1, y + 1, 5, 5);
      c.fillStyle = "#111"; c.fillRect(x + 2, y + 2, 3, 3);
    });
  })();

  function play(v) {
    if (v === "panel") {
      const el = document.querySelector("[data-v=panel] [data-count]"), end = +el.dataset.count, t0 = performance.now();
      (function f(t) {
        const p = Math.min((t - t0) / 1200, 1);
        el.textContent = "$" + (end * (1 - Math.pow(1 - p, 3))).toFixed(2);
        if (p < 1 && MODS[cur].v === "panel") requestAnimationFrame(f);
      })(t0);
    }
    if (v === "placa") {
      const out = $("dTyped"), sug = $("dSug"), txt = "P11";
      out.textContent = ""; sug.classList.remove("on");
      [...txt].forEach((ch, i) => later(() => out.textContent += ch, 500 + i * 300));
      later(() => sug.classList.add("on"), 600 + txt.length * 300);
    }
    if (v === "ia") {
      const cam = $("dCam"), read = $("dRead"), zt = $("dZoomTxt");
      cam.classList.remove("zoom", "shot"); read.classList.remove("on"); zt.textContent = "1×";
      $("z1").classList.add("on"); $("z2").classList.remove("on");
      later(() => { cam.classList.add("zoom"); zt.textContent = "2×"; $("z1").classList.remove("on"); $("z2").classList.add("on"); }, 900);
      later(() => cam.classList.add("shot"), 2600);
      later(() => read.classList.add("on"), 3300);
    }
    if (v === "entrada") {
      const modal = $("dEntryModal");
      modal.classList.remove("on");
      later(() => modal.classList.add("on"), 300);
    }
    if (v === "salida") {
      const modal = $("dExitModal"), shade = $("dExitShade"), btn = $("dPay"), toast = $("dToast");
      modal.classList.remove("on", "out"); shade.style.opacity = 1; toast.classList.remove("on"); btn.style.transform = "";
      later(() => modal.classList.add("on"), 300);
      later(() => btn.style.transform = "scale(.96)", 3600);
      later(() => { btn.style.transform = ""; modal.classList.add("out"); shade.style.opacity = 0; }, 3850);
      later(() => toast.classList.add("on"), 4150);
    }
  }

  function show(k) {
    timers.forEach(clearTimeout); timers = [];
    cur = k; const m = MODS[k];
    document.querySelectorAll(".dview").forEach(el => el.classList.toggle("on", el.dataset.v === m.v));
    document.querySelectorAll(".dnav [data-n]").forEach(el => el.classList.toggle("on", el.dataset.n === m.nav));
    $("tourCap").textContent = m.d;
    list.querySelectorAll(".tmod").forEach((b, i) => { b.classList.remove("on"); if (i === k) { void b.offsetWidth; b.classList.add("on"); } });
    chips.querySelectorAll("button").forEach((b, i) => b.classList.toggle("on", i === k));
    const chip = chips.children[k];
    if (chip && chips.offsetParent) chips.scrollTo({ left: chip.offsetLeft - 16, behavior: "smooth" });
    play(m.v);
    clearTimeout(timer);
    if (visible) timer = setTimeout(() => show((cur + 1) % MODS.length), DUR);
  }

  [list, chips].forEach(box => box.addEventListener("click", e => {
    const b = e.target.closest("[data-k]"); if (b) show(+b.dataset.k);
  }));
  // Pausa al pasar el mouse por el celular
  const phone = document.querySelector(".dphone");
  phone.addEventListener("mouseenter", () => { clearTimeout(timer); tour.classList.add("paused"); });
  phone.addEventListener("mouseleave", () => { tour.classList.remove("paused"); show(cur); });

  // Solo avanza cuando la sección está en pantalla
  new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible) show(cur < 0 ? 0 : cur); else clearTimeout(timer);
  }, { threshold: .35 }).observe(tour);
  show(0);
})();
