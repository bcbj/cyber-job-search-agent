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

CYBER_TITLE_PATTERNS = [
    r"\bsoc\s+(analyst|engineer|specialist|operator)\b",
    r"\bsecurity\s+(operations|monitoring)\s+(analyst|engineer|specialist)\b",
    r"\bcyber\s*security\s+(analyst|engineer|specialist|consultant)\b",
    r"\binformation\s+security\s+(analyst|engineer|specialist)\b",
    r"\bsecurity\s+analyst\b",
    r"\bthreat\s+(intelligence|hunter|hunting)\b",
    r"\bcyber\s+threat\s+intelligence\b",
    r"\bdetection\s+engineer\b",
    r"\bincident\s+(response|responder)\b",
    r"\bsecurity\s+engineer\b",
    r"\bsecurity\s+operations\b",
    r"\bsecurity\s+monitoring\b",
    r"\bcyber\s+defen[cs]e\b",
    r"\bcyber\s+fusion\b",
    r"\bmdr\s+(analyst|engineer|specialist)\b",
]

CYBER_TECH_PATTERNS = [
    r"\bsiem\b", r"\bedr\b", r"\bxdr\b", r"\bsplunk\b", r"\bsentinel\b",
    r"\bqradar\b", r"\bmitre\s+att&ck\b", r"\bthreat\s+hunt", r"\bthreat\s+intelligence\b",
    r"\bincident\s+response\b", r"\bdetection\s+engineering\b", r"\bmalware\s+analysis\b",
    r"\bindicator[s]?\s+of\s+(compromise|attack)\b", r"\bvulnerability\s+(management|intelligence)\b",
    r"\bsecurity\s+monitoring\b", r"\bsoc\b",
]

NON_CYBER_TITLE_PATTERNS = [
    r"\b(customer|client)\s+(service|success|support)\b", r"\bsales\b", r"\bmarketing\b",
    r"\brecruit(er|ing)\b", r"\bhuman\s+resources\b", r"\baccount(ant|ing)\b",
    r"\bfinance\b", r"\bnurs(e|ing)\b", r"\bteacher\b", r"\beducation\b",
    r"\bdriver\b", r"\bwarehouse\b", r"\bretail\b", r"\bconstruction\b",
    r"\breal\s+estate\b", r"\blegal\b", r"\bdata\s+entry\b", r"\bproject\s+manager\b",
    r"\bproduct\s+manager\b", r"\bsoftware\s+developer\b", r"\bweb\s+developer\b",
    r"\bhelp\s+desk\b", r"\bdesktop\s+support\b", r"\btechnical\s+support\b",
]

PART_TIME_PATTERNS = [
    r"\bpart[- ]time\b", r"\b10\s*(?:-|to)\s*20\s*hours?\b", r"\b(?:10|15|20)\s*hours?\s*(?:per|/)?\s*week\b",
    r"\bhours?\s+per\s+week\b", r"\bhrs?\s*/?\s*week\b", r"\bfractional\b",
]
REMOTE_PATTERNS = [r"\bremote\b", r"\bwork\s+from\s+home\b", r"\bworldwide\b", r"\banywhere\b"]
CONTRACT_ONLY_PATTERNS = [r"\bcontract\b", r"\btemporary\b", r"\btemp\b"]

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


def matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


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
    return [{"title": title, "url": f"{base}?{urlencode({'keywords': title, 'f_WT': '2', 'f_JT': 'P'})}"} for title in CONFIG["sources"]["linkedin"]["searches"]]


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


def filter_jobs(jobs: list[Job]) -> tuple[list[Job], dict[str, int]]:
    stats = {"retrieved": len(jobs), "duplicate_removed": 0, "non_cyber_title": 0, "no_cyber_technical_signal": 0, "not_part_time": 0, "not_remote": 0, "excluded_title": 0, "qualified": 0}
    unique: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        key = job.url.lower().strip() or f"{job.company.lower()}|{job.title.lower()}"
        if key in seen:
            stats["duplicate_removed"] += 1
            continue
        seen.add(key)
        job.description = clean(job.description)
        unique.append(job)

    qualified = []
    for job in unique:
        title = clean(job.title).lower()
        text = clean(f"{job.title} {job.description} {job.location}").lower()
        if matches_any(title, NON_CYBER_TITLE_PATTERNS):
            stats["excluded_title"] += 1
            continue
        if not matches_any(title, CYBER_TITLE_PATTERNS):
            stats["non_cyber_title"] += 1
            continue
        if not matches_any(text, CYBER_TECH_PATTERNS):
            stats["no_cyber_technical_signal"] += 1
            continue
        if not matches_any(text, PART_TIME_PATTERNS):
            stats["not_part_time"] += 1
            continue
        if not matches_any(text, REMOTE_PATTERNS):
            stats["not_remote"] += 1
            continue
        qualified.append(job)

    stats["qualified"] = len(qualified)
    return qualified, stats


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
        if matches_any(text, PART_TIME_PATTERNS): score += 15; reasons.append("explicit part-time signal")
        if matches_any(text, REMOTE_PATTERNS): score += 10; reasons.append("remote")
        score = min(score, 100)
        recommendation = "APPLY" if score >= 80 else "CONSIDER" if score >= 65 else "SKIP"
        scored.append({"job": asdict(job), "score": score, "recommendation": recommendation, "reasons": reasons})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[: CONFIG["ranking"]["max_results"]]


def ai_review(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items or not os.getenv("OPENAI_API_KEY"): return items
    client = OpenAI()
    prompt = "Review these already-filtered remote part-time cybersecurity jobs for an experienced SOC/CTI professional. Do not invent facts. Return JSON array with url, adjusted_score, why_match, concern, recommendation (APPLY/CONSIDER/SKIP). A job must remain genuinely cybersecurity-focused and explicitly part-time/fractional; do not promote a full-time role.\n" + json.dumps(items, ensure_ascii=False)
    try:
        response = client.responses.create(model="gpt-5-mini", input=prompt)
        review = json.loads(response.output_text)
        by_url = {x["job"]["url"]: x for x in items}
        for item in review:
            if item.get("url") in by_url: by_url[item["url"]].update(item)
    except Exception as exc:
        print(f"AI review unavailable: {exc}")
    return items


def render_report(items: list[dict[str, Any]], links: list[dict[str, str]], stats: dict[str, int]) -> str:
    now = datetime.now(timezone.utc).astimezone()
    lines = ["# Daily Remote Part-Time Cybersecurity Jobs", "", f"Generated: {now.strftime('%Y-%m-%d %H:%M %Z')}", "", "## Filter statistics", "", f"- Jobs retrieved: **{stats['retrieved']}**", f"- Duplicates removed: **{stats['duplicate_removed']}**", f"- Rejected — non-cybersecurity title: **{stats['non_cyber_title']}**", f"- Rejected — explicit non-cyber title: **{stats['excluded_title']}**", f"- Rejected — no technical cyber signal: **{stats['no_cyber_technical_signal']}**", f"- Rejected — no explicit part-time/fractional signal: **{stats['not_part_time']}**", f"- Rejected — not remote: **{stats['not_remote']}**", f"- **Qualified jobs: {stats['qualified']}**", ""]
    if not items: lines.append("No qualifying jobs were found in the configured automated sources today.")
    for i, item in enumerate(items, 1):
        job = item["job"]
        lines += [f"## {i}. {job['title']} — {job['company']}", f"**Score:** {item.get('adjusted_score', item['score'])}/100 | **Recommendation:** {item.get('recommendation', item['recommendation'])}", f"**Source:** {job['source']} | **Location:** {job['location']}", f"**Compensation:** {job['compensation'] or 'Not listed'}", f"**Why it matches:** {item.get('why_match', '; '.join(item['reasons']) or 'Limited matching information')}", f"**Concern:** {item.get('concern', 'Verify schedule and employment classification.')}", f"**Apply:** {job['url']}", ""]
    lines += ["## LinkedIn discovery searches", "", "These are direct LinkedIn searches for manual review; the agent does not scrape LinkedIn.", ""]
    for link in links: lines.append(f"- [{link['title']}]({link['url']})")
    return "\n".join(lines)


def main() -> None:
    jobs: list[Job] = []
    source_stats: dict[str, int] = {"remotive_retrieved": 0, "arbeitnow_retrieved": 0}
    for query in QUERIES:
        try:
            fetched = fetch_remotive(query); source_stats["remotive_retrieved"] += len(fetched); jobs.extend(fetched)
        except Exception as exc: print(f"Remotive error: {exc}")
        try:
            if CONFIG["sources"]["arbeitnow"]["enabled"]:
                fetched = fetch_arbeitnow(query); source_stats["arbeitnow_retrieved"] += len(fetched); jobs.extend(fetched)
        except Exception as exc: print(f"Arbeitnow error: {exc}")
    filtered, stats = filter_jobs(jobs)
    stats.update(source_stats)
    reviewed = ai_review(score_jobs(filtered))
    links = linkedin_search_links()
    latest_dir = Path("reports/latest"); latest_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "filter_statistics": stats, "jobs": reviewed, "linkedin_searches": links}
    report = render_report(reviewed, links, stats)
    latest_dir.joinpath("daily_report.md").write_text(report, encoding="utf-8")
    latest_dir.joinpath("daily_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path("reports").mkdir(exist_ok=True)
    Path("reports/daily_report.md").write_text(report, encoding="utf-8")
    Path("reports/daily_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Retrieved {stats['retrieved']} jobs; qualified {stats['qualified']} after cybersecurity, part-time, and remote filtering.")


if __name__ == "__main__": main()
