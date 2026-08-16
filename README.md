# Cyber Job Search Agent

Daily remote part-time cybersecurity job search agent.

## 🟢 Latest Job Search

The latest generated reports are published automatically after each successful GitHub Actions run.

- **[View latest Markdown report](reports/latest/daily_report.md) — human-readable**
- **[View latest JSON report](reports/latest/daily_report.json) — structured data**
- **[View report directory](reports/latest/)**
- **[View GitHub Actions runs](../../actions/workflows/daily-job-search.yml)**

The dashboard links above are intentionally generated from the persistent `reports/latest/` location so you do not have to hunt through completed workflow runs for the daily report.

## Schedule

The GitHub Actions workflow runs automatically at **6:00 AM Eastern Time every day**. GitHub Actions cron is UTC-only, so the workflow uses both 10:00 UTC and 11:00 UTC schedule entries plus an Eastern Time gate to account for daylight saving time. Manual `workflow_dispatch` runs execute immediately for testing.

## Focus

The agent prioritizes genuinely part-time remote roles matching an experienced cybersecurity profile, especially:

- SOC / Security Operations Analyst
- Cybersecurity Analyst
- Threat Intelligence Analyst
- Threat Hunter
- Detection Engineer
- Incident Response
- MDR / SOC operations
- Tier II / Tier III security operations

## Sources

Automated sources currently include:

- **Remotive** — remote-job API
- **Arbeitnow** — public job-board API
- **LinkedIn** — direct discovery searches for manual review; the agent does **not** scrape LinkedIn

LinkedIn searches are included in the daily Markdown report alongside automated job results.

## Output

Each successful run creates both:

- `reports/latest/daily_report.md` — readable daily report
- `reports/latest/daily_report.json` — structured daily data

The workflow also uploads both files as a GitHub Actions artifact retained for 30 days.

## Security

Store the OpenAI API key as the repository Actions secret `OPENAI_API_KEY`. Never commit API keys or a full resume to the repository.

## Manual Test

1. Open **Actions → Daily Cyber Job Search**.
2. Select **Run workflow** on the `main` branch.
3. Manual runs execute immediately.
4. After completion, use the **Latest Job Search** links above or open the workflow artifact.
