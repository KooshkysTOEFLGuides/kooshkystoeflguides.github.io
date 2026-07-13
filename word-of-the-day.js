(() => {
  "use strict";

  const archive = document.querySelector("[data-wotd-archive]");
  if (!archive) return;

  const debugMode = document.body.hasAttribute("data-wotd-debug");
  const searchInput = document.querySelector("[data-wotd-search]");
  const monthSelect = document.querySelector("[data-wotd-month]");
  const clearButton = document.querySelector("[data-wotd-clear]");
  const status = document.querySelector("[data-wotd-status]");
  const clock = document.querySelector("[data-wotd-clock]");

  const defaults = {
    timeZone: "Asia/Tehran",
    publishHour: 10,
    monthOrder: "desc",
    entryOrder: "asc"
  };

  const settings = {
    ...defaults,
    ...(window.KOOSHKY_WOTD_SETTINGS || {})
  };

  const monthFormatter = new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "long",
    timeZone: "UTC"
  });

  const fullDateFormatter = new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
    timeZone: "UTC"
  });

  const compactDateFormatter = new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  });

  function escapeHTML(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("en")
      .trim();
  }

  function parseISODate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
    if (!match) return null;

    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));

    if (
      date.getUTCFullYear() !== year ||
      date.getUTCMonth() !== month - 1 ||
      date.getUTCDate() !== day
    ) {
      return null;
    }

    return {
      iso: `${match[1]}-${match[2]}-${match[3]}`,
      year,
      month,
      day,
      date,
      dayKey: year * 10000 + month * 100 + day,
      monthKey: `${match[1]}-${match[2]}`
    };
  }

  function getZonedNow() {
    const formatter = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
      timeZone: settings.timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    });

    const parts = Object.fromEntries(
      formatter
        .formatToParts(new Date())
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)])
    );

    return {
      ...parts,
      dayKey: parts.year * 10000 + parts.month * 100 + parts.day
    };
  }

  function isPublished(item, now = getZonedNow()) {
    if (item.parsedDate.dayKey < now.dayKey) return true;
    if (item.parsedDate.dayKey > now.dayKey) return false;
    return now.hour >= Number(settings.publishHour);
  }

  function normalizeEntries(rawEntries) {
    const valid = [];

    (Array.isArray(rawEntries) ? rawEntries : []).forEach((raw, index) => {
      const word = String(raw?.word || "").trim();
      const href = String(raw?.href || "").trim();
      const parsedDate = parseISODate(raw?.date);

      if (!word || !href || !parsedDate) {
        console.warn(`Skipped invalid Word of the Day entry at index ${index}.`, raw);
        return;
      }

      const formattedDate = fullDateFormatter.format(parsedDate.date);
      const compactDate = compactDateFormatter.format(parsedDate.date);
      const monthDate = new Date(Date.UTC(parsedDate.year, parsedDate.month - 1, 1));
      const monthLabel = monthFormatter.format(monthDate);
      const shortMonthYear = new Intl.DateTimeFormat("en", {
        month: "short",
        year: "numeric",
        timeZone: "UTC"
      }).format(monthDate);

      valid.push({
        word,
        href,
        date: parsedDate.iso,
        parsedDate,
        formattedDate,
        compactDate,
        monthLabel,
        shortMonthYear,
        searchText: normalizeText([
          word,
          parsedDate.iso,
          compactDate,
          formattedDate,
          monthLabel,
          `${parsedDate.day}/${parsedDate.month}/${parsedDate.year}`,
          `${parsedDate.month}/${parsedDate.day}/${parsedDate.year}`
        ].join(" "))
      });
    });

    const dates = new Map();
    valid.forEach((item) => {
      if (dates.has(item.date)) {
        console.warn(
          `More than one Word of the Day entry uses ${item.date}.`,
          dates.get(item.date),
          item
        );
      } else {
        dates.set(item.date, item);
      }
    });

    return valid;
  }

  function sortEntries(entries) {
    const direction = settings.entryOrder === "desc" ? -1 : 1;

    return [...entries].sort((a, b) => {
      const dateComparison = a.date.localeCompare(b.date) * direction;
      if (dateComparison !== 0) return dateComparison;
      return a.word.localeCompare(b.word, "en", { sensitivity: "base" });
    });
  }

  function sortMonthKeys(keys) {
    const direction = settings.monthOrder === "asc" ? 1 : -1;
    return [...keys].sort((a, b) => a.localeCompare(b) * direction);
  }

  function getAvailableEntries() {
    const now = getZonedNow();
    const all = normalizeEntries(window.KOOSHKY_WORDS || []);

    return {
      now,
      all,
      available: debugMode ? all : all.filter((item) => isPublished(item, now))
    };
  }

  function populateMonthFilter(entries) {
    if (!monthSelect) return;

    const selected = monthSelect.value;
    const monthMap = new Map();

    entries.forEach((item) => {
      if (!monthMap.has(item.parsedDate.monthKey)) {
        monthMap.set(item.parsedDate.monthKey, item.monthLabel);
      }
    });

    const options = sortMonthKeys(monthMap.keys())
      .map((key) => `<option value="${escapeHTML(key)}">${escapeHTML(monthMap.get(key))}</option>`)
      .join("");

    monthSelect.innerHTML = `<option value="">All months</option>${options}`;

    if (monthMap.has(selected)) {
      monthSelect.value = selected;
    }
  }

  function entryMarkup(item, published) {
    const scheduledLabel = debugMode && !published
      ? `<span class="wotd-scheduled">Scheduled</span>`
      : "";

    return `
      <article class="wotd-entry${published ? "" : " is-scheduled"}">
        <div class="wotd-day" aria-hidden="true">
          <strong>${escapeHTML(item.parsedDate.day)}</strong>
          <span>${escapeHTML(item.shortMonthYear)}</span>
        </div>

        <div class="wotd-entry-copy">
          <div class="wotd-entry-meta">
            <time datetime="${escapeHTML(item.date)}">${escapeHTML(item.formattedDate)}</time>
            ${scheduledLabel}
          </div>
          <h3><a href="${escapeHTML(item.href)}">${escapeHTML(item.word)}</a></h3>
        </div>

        <a class="text-link wotd-open" href="${escapeHTML(item.href)}">
          Open entry <span aria-hidden="true">→</span>
        </a>
      </article>`;
  }

  function groupMarkup(monthKey, items, groupIndex, filtersActive, now) {
    const label = items[0]?.monthLabel || monthKey;
    const shouldOpen = filtersActive || groupIndex === 0;

    return `
      <details class="wotd-month" ${shouldOpen ? "open" : ""}>
        <summary>
          <span>${escapeHTML(label)}</span>
          <span class="count">${items.length} ${items.length === 1 ? "word" : "words"}</span>
        </summary>
        <div class="wotd-list">
          ${items.map((item) => entryMarkup(item, isPublished(item, now))).join("")}
        </div>
      </details>`;
  }

  function updateClock(now) {
    if (!clock) return;

    const hour = String(now.hour).padStart(2, "0");
    const minute = String(now.minute).padStart(2, "0");
    clock.textContent = `Archive time: ${hour}:${minute} (${settings.timeZone})`;
  }

  function render() {
    const { now, all, available } = getAvailableEntries();
    updateClock(now);
    populateMonthFilter(available);

    const query = normalizeText(searchInput?.value);
    const selectedMonth = monthSelect?.value || "";
    const filtersActive = Boolean(query || selectedMonth);

    const filtered = sortEntries(available).filter((item) => {
      const queryMatch = !query || item.searchText.includes(query);
      const monthMatch = !selectedMonth || item.parsedDate.monthKey === selectedMonth;
      return queryMatch && monthMatch;
    });

    const groups = new Map();
    filtered.forEach((item) => {
      const key = item.parsedDate.monthKey;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });

    const monthKeys = sortMonthKeys(groups.keys());

    if (!filtered.length) {
      const hasAnyAvailable = available.length > 0;
      archive.innerHTML = `
        <div class="empty-state empty-state-large">
          <h2>${hasAnyAvailable ? "No matching words." : debugMode ? "No words have been added yet." : "No published words yet."}</h2>
          <p>${hasAnyAvailable ? "Try a different word, date, or month." : "Add entries to word-data.js."}</p>
        </div>`;
    } else {
      archive.innerHTML = monthKeys
        .map((key, index) => groupMarkup(key, groups.get(key), index, filtersActive, now))
        .join("");
    }

    if (status) {
      if (debugMode) {
        const scheduled = all.filter((item) => !isPublished(item, now)).length;
        status.textContent = `${filtered.length} shown · ${available.length} total · ${scheduled} scheduled`;
      } else {
        status.textContent = `${filtered.length} ${filtered.length === 1 ? "word" : "words"} shown`;
      }
    }
  }

  [searchInput, monthSelect].forEach((control) => {
    control?.addEventListener("input", render);
    control?.addEventListener("change", render);
  });

  clearButton?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    if (monthSelect) monthSelect.value = "";
    render();
    searchInput?.focus();
  });

  window.addEventListener("focus", render);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) render();
  });

  // Recheck publication status regularly so today's word appears at 10:00
  // without requiring the visitor to reload the page.
  window.setInterval(render, 60_000);

  render();
})();
