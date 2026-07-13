# Word of the Day section

Upload these five files to the root of the GitHub Pages repository:

- `word-of-the-day.html`
- `word-data.js`
- `word-of-the-day.js`
- `word-of-the-day.css`
- `wotd-schedule-preview-7c4a91e2f6.html`

The pages reuse the site's existing `styles.css`, `site.js`, and `images/` files.

## Add a word

Edit `word-data.js` and add an object inside `window.KOOSHKY_WORDS`:

```js
{
  word: "Meticulous",
  date: "2026-07-17",
  href: "WordOfTheDay/meticulous.html",
  partOfSpeech: "adjective",
  summary: "Very careful and attentive to small details."
}
```

Separate entries with commas. Dates may be skipped. The archive groups whatever exists by month.

## Publication timing

The public page reveals an entry at 10:00 AM in `Asia/Tehran` on its date. It rechecks once a minute, when the tab becomes active, and when the browser window regains focus.

## Private preview limitation

The preview page is not linked anywhere and asks search engines not to index it. However, GitHub Pages is a static site. If `word-data.js` is deployed publicly, a technically knowledgeable visitor can inspect that file and see scheduled entries. Client-side JavaScript can hide future words from the normal interface, but it cannot make public source data truly secret.
