from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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


def clean(value: str) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def fetch_remotive(query: str) -> list[Job]:
    response = requests.get("https://remotive.com/api/remote-jobs", params={"search": query}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return [Job(j.get("title", ""), j.get("company_name", ""), j.get("url", ""), j.get("description", ""), j.get("candidate_required_location", "Remote"), j.get("salary", ""), "Remotive") for j in response.json().get("jobs", [])]


def fetch_arbeitnow(query: str) -> list[Job]:
    response = requests.get(CONFIG["sources"]["arbeitnow"]["api_url"], headers=HEADERS, timeout=30)
    response.raise_for_status()
    jobs = response.json().get("data", [])
    terms = [x.lower() for x in re.findall(r"[a-zA-Z]+", query) if len(x) > 2]
    result = []
    for j in jobs:
        text = clean(f"{j.get('title','')} {j.get('description','')} {j.get('tags','')}").lower()
        if any(term in text for term in terms):
            result.append(Job(j.get("title", ""), j.get("company_name", j.get("company", "")), j.get("url", ""), j.get("description", ""), j.get("location", "Remote"), j.get("salary", ""), "Arbeitnow"))
    return result


def linkedin_search_links() -> list[dict[str, str]]:
    base = CONFIG["sources"]["linkedin"]["search_base_url"]
    links = []
    for title in CONFIG["sources"]["linkedin"]["searches"]:
        params = {"keywords": title, "f_WT": "2", "f_JT": "P"}
        links.append({"title": title, "url": f"{base}?{urlencode(params)}"})
    return links


def dedupe(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    result = []
    for job in jobs:
        job.description = clean(job.description)
        key = job.url.lower().strip() or f"{job.company.lower()}|{job.title.lower()}"
        if key not in seen:
            seen.add(key)
            result.append(job)
    return result


def is_candidate(job: Job) -> bool:
    text = f"{job.title} {job.description} {job.location}".lower()
    if any(term.lower() in text for term in CONFIG["search"]["exclude"]):
        return False
    part_time = any(term in text for term in ("part-time", "part time", "hours per week", "hrs/week", "fractional", "contract"))
    remote = "remote" in text or "worldwide" in text
    return remote and part_time


def score_jobs(jobs: list[Job]) -> list[dict[str, Any]]:
    strengths = CONFIG["candidate"]["strengths"]
    titles = CONFIG["search"]["titles"]
    scored = []
    for job in jobs:
        text = f"{job.title} {job.description}".lower()
        score, reasons = 0, []
        if any(t.lower() in job.title.lower() for t in titles): score += 30; reasons.append("target title")
        matches = [s for s in strengths if s.lower() in text]
        score += min(45, len(matches) * 5)
        if matches: reasons.append("skills: " + ", ".join(matches[:6]))
        if any(x in text for x in ("part-time", "part time", "fractional")): score += 15; reasons.append("part-time signal")
        if "contract" in text: score += 5; reasons.append("contract signal")
        if "remote" in text or "worldwide" in text: score += 10; reasons.append("remote")
        score = min(score, 100)
        recommendation = "APPLY" if score >= 80 else "CONSIDER" if score >= 65 else "SKIP"
        scored.append({"job": asdict(job), "score": score, "recommendation": recommendation, "reasons": reasons})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[: CONFIG["ranking"]["max_results"]]


def ai_review(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items or not os.getenv("OPENAI_API_KEY"): return items
    client = OpenAI()
    prompt = "Review these remote part-time cybersecurity jobs for an experienced SOC/CTI professional. Do not invent facts. Return JSON array with url, adjusted_score, why_match, concern, recommendation (APPLY/CONSIDER/SKIP). Prefer genuinely part-time SOC, CTI, threat hunting, detection engineering, IR, SIEM/EDR and MITRE ATT&CK roles.\n" + json.dumps(items, ensure_ascii=False)
    try:
        response = client.responses.create(model="gpt-5-mini", input=prompt)
        review = json.loads(response.output_text)
        by_url = {x["job"]["url"]: x for x in items}
        for item in review:
            if item.get("url") in by_url: by_url[item["url"]].update(item)
    except (json.JSONDecodeError, Exception) as exc:
        print(f"AI review unavailable: {exc}")
    return items


def render_report(items: list[dict[str, Any]], links: list[dict[str, str]]) -> str:
    now = datetime.now(timezone.utc).astimezone()
    lines = ["# Daily Remote Part-Time Cybersecurity Jobs", "", f"Generated: {now.strftime('%Y-%m-%d %H:%M %Z')}", ""]
    if not items: lines.append("No qualifying jobs were found in the configured automated sources today.")
    for i, item in enumerate(items, 1):
        job = item["job"]
        lines += [f"## {i}. {job['title']} — {job['company']}", f"**Score:** {item.get('adjusted_score', item['score'])}/100 | **Recommendation:** {item.get('recommendation', item['recommendation'])}", f"**Source:** {job['source']} | **Location:** {job['location']}", f"**Compensation:** {job['compensation'] or 'Not listed'}", f"**Why it matches:** {item.get('why_match', '; '.join(item['reasons']) or 'Limited matching information')}", f"**Concern:** {item.get('concern', 'Verify schedule and employment classification.')}", f"**Apply:** {job['url']}", ""]
    lines += ["## LinkedIn discovery searches", "", "These are direct LinkedIn searches for manual review; the agent does not scrape LinkedIn.", ""]
    for link in links: lines.append(f"- [{link['title']}]({link['url']})")
    return "\n".join(lines)


def main() -> None:
    jobs: list[Job] = []
    for query in QUERIES:
        try:
            jobs.extend(fetch_remotive(query))
        except Exception as exc: print(f"Remotive error: {exc}")
        try:
            if CONFIG["sources"]["arbeitnow"]["enabled"]: jobs.extend(fetch_arbeitnow(query))
        except Exception as exc: print(f"Arbeitnow error: {exc}")
    ranked = score_jobs([j for j in dedupe(jobs) if is_candidate(j)])
    reviewed = ai_review(ranked)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/daily_report.md").write_text(render_report(reviewed, linkedin_search_links()), encoding="utf-8")
    Path("reports/daily_report.json").write_text(json.dumps({"jobs": reviewed, "linkedin_searches": linkedin_search_links()}, indent=2), encoding="utf-8")
    print(f"Found {len(reviewed)} qualifying jobs from automated sources.")


if __name__ == "__main__": main()
