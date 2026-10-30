# GameNight Guide (v0.1)

Static where-to-watch site for NFL + NBA. The data comes from ESPN's public scoreboard JSON. No key is needed.

- `python3 build.py`: fetches the next 7 days and writes `site/` (home page, `/nfl/<team>/`, `/nba/<team>/`, `games.json`, `build-report.json`) and `email/monday-email.{md,html}`.
- `config.json`: affiliate link slots and the newsletter endpoint. **Every `PLACEHOLDER_*` value is a placeholder, not a real ID.** While a slot is a placeholder, links point to the service's normal homepage and carry `data-affiliate-slot`.
- Local preview: `python3 -m http.server 8787 -d site`
- To keep it fresh, run `build.py` on a schedule (for example a daily GitHub Actions cron) and redeploy `site/`.
- No prices are shown. None have been verified from the services' own pages yet.
