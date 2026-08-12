# docs/manual-qa-checklist.md

Run through this before every `prod` deploy (spec §11).

## Discovery dashboards
- [ ] All four panels (Top Gainers, Top Losers, Top Volume, Volume Breakout) render 10 rows each
- [ ] Panels are read-only — clicking a row does nothing
- [ ] Panels refresh roughly every 30 min during market hours; no refresh 8pm-4am ET

## Watchlist
- [ ] Adding a valid ticker succeeds; adding an invalid ticker shows an inline error, doesn't add
- [ ] Adding a 31st symbol is rejected with a clear error
- [ ] Removing a symbol removes its row immediately
- [ ] Clicking a row opens the detail modal without a page navigation

## Detail modal
- [ ] Pipeline nodes are color-differentiated by freshness (a just-updated Sentiment node looks
      visually distinct from an hour-old Fundamentals node)
- [ ] Results chart, claims, and verdict/confidence render
- [ ] Closing the modal (backdrop click) never triggers a network POST/pipeline run — confirm via
      browser devtools network tab

## Chat + news feed
- [ ] A cross-symbol question (mentioning two watchlist symbols) gets a grounded answer
- [ ] The answer never phrases the score as investment advice
- [ ] New articles appear in the live news feed within ~1-2s of being detected

## Live pipeline visualizer
- [ ] Opening it for a symbol mid-run shows nodes transitioning idle → running → finished in the
      correct dependency order (four specialists in parallel, then Bull/Bear in parallel, then Risk, then Manager)
- [ ] Clicking a finished node shows what it produced
