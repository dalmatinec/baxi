// satpaev.ceo: печать кода, живой чат, живые цифры, вкладки команд, появление блоков.
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));

  // ---------- меню на телефоне ----------
  // меню на телефоне: открывается бургером, закрывается по нажатию на пункт, мимо меню или Esc
  const burger = document.querySelector(".burger");
  const menu = document.querySelector(".menu");
  if (burger && menu) {
    const close = () => { menu.classList.remove("open"); burger.textContent = "☰"; };
    burger.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = menu.classList.toggle("open");
      burger.textContent = open ? "✕" : "☰";
    });
    menu.querySelectorAll("a").forEach((a) => a.addEventListener("click", close));
    document.addEventListener("click", (e) => { if (!menu.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    window.addEventListener("scroll", () => { if (menu.classList.contains("open")) close(); }, { passive: true });
  }

  // вкладки Store: обмен, NFT, звёзды, Premium, юзернеймы
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", (e) => {
    e.preventDefault();
    const box = c.closest(".card");
    box.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === c));
    box.querySelectorAll(".chip-text").forEach((t) => t.classList.toggle("hidden", t.dataset.text !== c.dataset.chip));
  }));

  // ---------- живые цифры от бота ----------
  fetch("/stats.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((s) => {
      const fmt = (n) => Number(n || 0).toLocaleString("ru-RU");
      document.querySelectorAll("[data-stat]").forEach((el) => (el.textContent = fmt(s[el.dataset.stat])));
    })
    .catch(() => document.querySelectorAll(".stat-live").forEach((el) => el.remove()));

  // ---------- появление при прокрутке ----------
  const io = new IntersectionObserver((items) => items.forEach((it) => {
    if (it.isIntersecting) { it.target.classList.add("in"); io.unobserve(it.target); }
  }), { threshold: 0.12 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

  // ---------- вкладки и копирование команд ----------
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll("[data-tab]").forEach((el) => el.classList.toggle("hidden", el.dataset.tab !== b.dataset.show));
  }));
  document.querySelectorAll(".cmd").forEach((c) => c.addEventListener("click", () => {
    const text = c.querySelector("code").textContent;
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.resolve()).finally(() => {
      c.classList.add("copied");
      setTimeout(() => c.classList.remove("copied"), 1200);
    });
  }));

  // ---------- сцена: печатаем код, потом бот оживает в чате ----------
  const pre = document.querySelector("#code");
  const feed = document.querySelector("#feed");
  if (!feed) return;

  const SCENES = [
    {
      file: "baxi.py",
      code: [
        [["k", "from"], ["", " baxi "], ["k", "import"], ["", " Bot"]],
        [],
        [["", "bot = "], ["f", "Bot"], ["", "(chat="], ["s", '"Наш чат"'], ["", ")"]],
        [["", "bot.character = "], ["s", '"дерзкий, но добрый"']],
        [["", "bot.memory = "], ["n", "True"], ["c", "   # помнит всех в чате"]],
        [["", "bot."], ["f", "launch"], ["", "()"], ["c", "        # поехали 🚀"]],
      ],
      chat: [
        ["Аня", "#e8833a", "кто сегодня идёт гулять?"],
        ["Олег", "#3b82f6", "я буду к 9, ждите"],
        ["Бакси", "bot", "олег опять опоздает на час, ставлю на это 😏"],
        ["Тимур", "#16a34a", "бакси, куда сходить вечером?"],
        ["Бакси", "bot", "в кино на что-нибудь страшное, а потом пиццу. классика 🔥"],
      ],
    },
    {
      file: "games.py",
      code: [
        [["c", "# игры и фишки, всё включается кнопками"]],
        [["", "bot."], ["f", "quiz"], ["", "(topic="], ["s", '"кино"'], ["", ", questions="], ["n", "10"], ["", ")"]],
        [["", "bot."], ["f", "results"], ["", "(at="], ["s", '"23:00"'], ["", ")"], ["c", "  # итоги дня"]],
        [["", "bot."], ["f", "call"], ["", "(every="], ["n", "5"], ["", ", text="], ["s", '"🎮 игра!"'], ["", ")"]],
      ],
      chat: [
        ["Дина", "#db2777", "/call"],
        ["Бакси", "bot", "🎮 игра началась, заходите! Аня, Олег, Тимур, Саша, Дина"],
        ["Саша", "#7c3aed", "бакси, кто сегодня самый болтливый?"],
        ["Бакси", "bot", "олег, 214 сообщений. брат, ты вообще работаешь? 😂"],
      ],
    },
  ];

  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const fileLabel = document.querySelector("#file");

  async function typeScene(scene) {
    if (!pre) return;
    if (fileLabel) fileLabel.textContent = scene.file;
    pre.innerHTML = "";
    for (const line of scene.code) {
      for (const [cls, text] of line) {
        const span = document.createElement("span");
        if (cls) span.className = "tok-" + cls;
        pre.appendChild(span);
        for (const ch of text) {
          span.textContent += ch;
          await sleep(ch === " " ? 18 : 34 + Math.random() * 30);
        }
      }
      pre.appendChild(document.createTextNode("\n"));
      await sleep(160);
    }
  }

  async function playChat(scene) {
    feed.innerHTML = "";
    for (const [who, color, text] of scene.chat) {
      if (color === "bot") {
        const t = document.createElement("div");
        t.className = "typing";
        t.innerHTML = "<i></i><i></i><i></i>";
        feed.appendChild(t);
        await sleep(1100);
        t.remove();
      } else {
        await sleep(650);
      }
      const m = document.createElement("div");
      m.className = "msg" + (color === "bot" ? " bot" : "");
      const c = color === "bot" ? (document.body.classList.contains("baxi") ? "#7c3aed" : "#ff6b4a") : color;
      m.innerHTML = `<span class="who" style="color:${c}">${esc(who)}</span>${esc(text)}`;
      feed.appendChild(m);
      while (feed.children.length > 5) feed.firstElementChild.remove();
    }
  }

  async function loop() {
    const caret = document.createElement("span");
    caret.className = "caret";
    for (let i = 0; ; i = (i + 1) % SCENES.length) {
      await typeScene(SCENES[i]);
      if (pre) pre.appendChild(caret);
      await playChat(SCENES[i]);
      await sleep(3200);
      if (reduce) break;
    }
  }
  loop();
})();
