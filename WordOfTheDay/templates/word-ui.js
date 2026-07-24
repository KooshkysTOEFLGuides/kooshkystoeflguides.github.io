(() => {
  "use strict";

  const root = document.documentElement;
  root.classList.add("js");

  const storageKey = "kooshky-wotd-theme";
  const themeButton = document.querySelector("[data-theme-toggle]");
  const topButton = document.querySelector("[data-back-to-top]");
  const audioButtons = document.querySelectorAll("[data-pronunciation-button]");
  const statusNode = document.querySelector("[data-audio-status]");

  const applyTheme = (theme) => {
    if (theme === "light" || theme === "dark") root.dataset.theme = theme;
    else delete root.dataset.theme;

    if (themeButton) {
      const active = root.dataset.theme || "system";
      themeButton.textContent = active === "dark" ? "Light mode" : "Dark mode";
      themeButton.setAttribute("aria-label", `Switch from ${active} theme`);
    }
  };

  let savedTheme = null;
  try { savedTheme = localStorage.getItem(storageKey); } catch (_) { /* nonessential */ }
  applyTheme(savedTheme);

  themeButton?.addEventListener("click", () => {
    const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const current = root.dataset.theme || (systemDark ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem(storageKey, next); } catch (_) { /* local files may block storage */ }
  });

  const speakWithBrowser = (phrase, button) => {
    if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
      if (statusNode) statusNode.textContent = "The audio file is unavailable and this browser has no speech fallback.";
      window.location.href = button.href;
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(phrase);
    utterance.lang = "en-US";
    utterance.rate = 0.88;
    utterance.onstart = () => {
      button.classList.add("is-playing");
      if (statusNode) statusNode.textContent = "Using the browser voice because the local MP3 was unavailable.";
    };
    utterance.onend = utterance.onerror = () => button.classList.remove("is-playing");
    window.speechSynthesis.speak(utterance);
  };

  audioButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const phrase = button.dataset.pronunciationPhrase || "";
      const src = button.dataset.audioSrc || button.getAttribute("href") || "";
      let fallbackStarted = false;

      const fallback = () => {
        if (fallbackStarted) return;
        fallbackStarted = true;
        speakWithBrowser(phrase, button);
      };

      const audio = new Audio();
      audio.preload = "auto";
      audio.src = src;
      audio.addEventListener("play", () => {
        button.classList.add("is-playing");
        if (statusNode) statusNode.textContent = `Playing local pronunciation: “${phrase}”.`;
      }, { once: true });
      audio.addEventListener("ended", () => button.classList.remove("is-playing"), { once: true });
      audio.addEventListener("error", fallback, { once: true });

      const playResult = audio.play();
      if (playResult && typeof playResult.catch === "function") playResult.catch(fallback);
    });
  });

  if (topButton) {
    const updateTopButton = () => topButton.classList.toggle("visible", window.scrollY > 700);
    window.addEventListener("scroll", updateTopButton, { passive: true });
    updateTopButton();
    topButton.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  }
})();
