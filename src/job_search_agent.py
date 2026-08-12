from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from openai import OpenAI

CONFIG = yaml.safe_load(Path("config/search_config.yml").read_text(encoding="utf-8"))

QUERIES = [
    "remote part-time SOC analyst cybersecurity",
    "remote part-time security operations analyst",
    "remote part-time cybersecurity analyst",
    "remote part-time threat intelligence analyst",
    "remote part-time threat hunter detection engineer",
]

HEADERS = {"User-Agent": "cyber-job-search-agent/1.0"}

@dataclass
class Job:
    title: str
    company: str
    url: str
    description: str = ""
    location: str = "Remote"
    compensation: str = ""
    source: str = ""


def fetch_remotive(query: str) -> list[Job]:
    url = "https://remotive.com/api/remote-jobs"
    response = requests.get(url, params={"search": query}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    return [
        Job(
            title=j.get("title", ""),
            company=j.get("company_name", ""),
            url=j.get("url", ""),
            description=j.get("description", ""),
            location=j.get("candidate_required_location", "Remote"),
            compensation=j.get("salary", ""),
            source="Remotive",
        )
        for j in jobs
    ]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def dedupe(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    result = []
    for job in jobs:
        key = job.url.lower().strip() or f"{job.company.lower()}|{job.title.lower()}"
        if key not in seen:
            seen.add(key)
            job.description = normalize_text(job.description)
            result.append(job)
    return result


def is_candidate(job: Job) -> bool:
    text = f"{job.title} {job.description}".lower()
    excluded = CONFIG["search"]["exclude"]
    if any(term.lower() in text for term in excluded):
        return False
    part_time = any(term in text for term in ("part-time", "part time", "hours per week", "hrs/week", "fractional", "contract"))
    remote = "remote" in f"{job.location} {text}".lower()
    return remote and part_time


def score_jobs(jobs: list[Job]) -> list[dict[str, Any]]:
    strengths = CONFIG["candidate"]["strengths"]
    titles = CONFIG["search"]["titles"]
    scored = []
    for job in jobs:
        text = f"{job.title} {job.description}".lower()
        score = 0
        reasons = []
        if any(t.lower() in job.title.lower() for t in titles):
            score += 30
            reasons.append("target title")
        matches = [s for s in strengths if s.lower() in text]
        score += min(45, len(matches) * 5)
        if matches:
            reasons.append("skills: " + ", ".join(matches[:6]))
        if any(x in text for x in ("part-time", "part time", "fractional")):
            score += 15
            reasons.append("part-time signal")
        if "contract" in text:
            score += 5
            reasons.append("contract signal")
        if "remote" in text or "remote" in job.location.lower():
            score += 10
            reasons.append("remote")
        score = min(score, 100)
        recommendation = "APPLY" if score >= 80 else "CONSIDER" if score >= 65 else "SKIP"
        scored.append({"job": asdict(job), "score": score, "recommendation": recommendation, "reasons": reasons})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[: CONFIG["ranking"]["max_results"]]


def ai_review(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items or not os.getenv("OPENAI_API_KEY"):
        return items
    client = OpenAI()
    payload = json.dumps(items, ensure_ascii=False)
    prompt = (
        "Review these candidate remote part-time cybersecurity jobs for an experienced SOC/CTI professional. "
        "Do not invent facts. Preserve URLs. For each item, return concise fields: adjusted_score (0-100), "
        "why_match, concern, and recommendation (APPLY/CONSIDER/SKIP). Prefer genuinely part-time roles and "
        "strong alignment with SOC, threat intelligence, threat hunting, detection engineering, incident response, "
        "SIEM/EDR and MITRE ATT&CK. Input JSON follows:\n" + payload
    )
    response = client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )
    text = response.output_text
    try:
        review = json.loads(text)
        by_url = {x["job"]["url"]: x for x in items}
        for item in review:
            original = by_url.get(item.get("url"))
            if original:
                original.update(item)
    except json.JSONDecodeError:
        pass
    return items


def render_report(items: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).astimezone()
    lines = [
        "# Daily Remote Part-Time Cybersecurity Jobs",
        "",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
    ]
    if not items:
        lines.append("No qualifying jobs were found in the configured sources today.")
        return "\n".join(lines)
    for i, item in enumerate(items, 1):
        job = item["job"]
        lines += [
            f"## {i}. {job['title']} — {job['company']}",
            f"**Score:** {item.get('adjusted_score', item['score'])}/100  |  **Recommendation:** {item.get('recommendation', item['recommendation'])}",
            f"**Source:** {job['source']}  |  **Location:** {job['location']}",
            f"**Compensation:** {job['compensation'] or 'Not listed'}",
            f"**Why it matches:** {item.get('why_match', '; '.join(item['reasons']) or 'Limited matching information')}",
            f"**Concern:** {item.get('concern', 'Review schedule and employment classification on the posting.')}",
            f"**Apply:** {job['url']}",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    jobs: list[Job] = []
    for query in QUERIES:
        try:
            jobs.extend(fetch_remotive(query))
        except Exception as exc:
            print(f"Source error for {query!r}: {exc}")
    jobs = [j for j in dedupe(jobs) if is_candidate(j)]
    ranked = score_jobs(jobs)
    reviewed = ai_review(ranked)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/daily_report.md").write_text(render_report(reviewed), encoding="utf-8")
    Path("reports/daily_report.json").write_text(json.dumps(reviewed, indent=2), encoding="utf-8")
    print(f"Found {len(reviewed)} qualifying jobs.")


if __name__ == "__main__":
    main()
