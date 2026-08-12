# Cyber Job Search Agent

Daily remote part-time cybersecurity job search agent.

## Schedule

The GitHub Actions workflow is configured for **6:00 AM Eastern Time every day**. The cron expression uses UTC and the workflow accounts for daylight-saving time by running at 10:00 UTC during EDT; a second scheduled entry is used for 11:00 UTC during EST. Because GitHub Actions cron is UTC-only, the workflow documents the DST behavior explicitly.

## Focus

The agent prioritizes genuinely part-time remote roles matching a senior cybersecurity profile, especially:

- SOC / Security Operations Analyst
- Cybersecurity Analyst
- Threat Intelligence Analyst
- Threat Hunter
- Detection Engineer
- Incident Response
- MDR / SOC operations
- Tier II / Tier III security operations

## Security

Store the OpenAI API key as the repository Actions secret `OPENAI_API_KEY`. Never commit API keys or a full resume to the repository.

## Output

Each run generates a Markdown report and uploads it as a GitHub Actions artifact. The report includes job title, company, URL, compensation when available, schedule, match score, rationale, and application recommendation.
