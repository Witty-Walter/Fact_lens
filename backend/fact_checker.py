import os
import json
from typing import Dict, Any, List, Tuple

from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY in .env")

if not TAVILY_API_KEY:
    raise ValueError("Missing TAVILY_API_KEY in .env")

groq_client = Groq(api_key=GROQ_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)


def retrieve_evidence(
    claim: str,
    max_results: int = 5
) -> Tuple[List[str], List[Dict[str, str]]]:
    response = tavily_client.search(
        query=claim,
        search_depth="advanced",
        max_results=max_results
    )

    results = response.get("results", [])

    evidence_chunks: List[str] = []
    source_items: List[Dict[str, str]] = []

    for item in results:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        url = (item.get("url") or "").strip()

        if content:
            evidence_chunks.append(
                f"Title: {title}\nURL: {url}\nSnippet: {content}"
            )

        if url:
            source_items.append({
                "title": title if title else url,
                "url": url
            })

    return evidence_chunks, source_items


def build_prompt(claim: str, evidence_text: str) -> str:
    return f"""
You are a careful evidence-grounded fact-checking assistant.

Rules:
- Evaluate the claim using ONLY the evidence provided below.
- Do not use outside knowledge.
- If the evidence is weak, incomplete, conflicting, or not enough, return "Uncertain".
- Use "Misleading" when a claim is partly true but misses important context.
- Confidence must be between 0 and 1.
- Keep the explanation short, clear, and practical.
- Return ONLY valid JSON.

Output format:
{{
  "verdict": "True" | "False" | "Misleading" | "Uncertain",
  "confidence": 0.0,
  "explanation": "short explanation",
  "sources": [
    {{
      "title": "source title",
      "url": "https://example.com"
    }}
  ]
}}

Claim:
{claim}

Evidence:
{evidence_text}
""".strip()


def run_fact_check(claim: str) -> Dict[str, Any]:
    claim = (claim or "").strip()

    if not claim:
        return {
            "verdict": "Uncertain",
            "confidence": 0.0,
            "explanation": "No claim text was provided.",
            "sources": []
        }

    try:
        evidence_chunks, source_items = retrieve_evidence(claim)

        if not evidence_chunks:
            return {
                "verdict": "Uncertain",
                "confidence": 0.2,
                "explanation": "No relevant evidence could be retrieved.",
                "sources": []
            }

        evidence_text = "\n\n".join(evidence_chunks[:5])
        prompt = build_prompt(claim, evidence_text)

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful fact-checking assistant. Return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        output_text = response.choices[0].message.content.strip()

        try:
            result = json.loads(output_text)
        except Exception:
            return {
                "verdict": "Uncertain",
                "confidence": 0.3,
                "explanation": "Model returned invalid JSON.",
                "sources": source_items[:3]
            }

        if "verdict" not in result:
            result["verdict"] = "Uncertain"

        if "confidence" not in result:
            result["confidence"] = 0.3

        if "explanation" not in result:
            result["explanation"] = "No explanation returned."

        if "sources" not in result or not isinstance(result["sources"], list):
            result["sources"] = source_items[:3]

        if not result["sources"]:
            result["sources"] = source_items[:3]

        cleaned_sources: List[Dict[str, str]] = []
        for source in result["sources"]:
            if isinstance(source, dict):
                title = str(source.get("title", "")).strip()
                url = str(source.get("url", "")).strip()

                if url:
                    cleaned_sources.append({
                        "title": title if title else url,
                        "url": url
                    })

        if not cleaned_sources:
            cleaned_sources = source_items[:3]

        result["sources"] = cleaned_sources

        try:
            result["confidence"] = float(result["confidence"])
        except Exception:
            result["confidence"] = 0.3

        result["confidence"] = max(0.0, min(1.0, result["confidence"]))

        allowed_verdicts = {"True", "False", "Misleading", "Uncertain"}
        if result["verdict"] not in allowed_verdicts:
            result["verdict"] = "Uncertain"

        return result

    except Exception as e:
        return {
            "verdict": "Uncertain",
            "confidence": 0.1,
            "explanation": f"Fact check failed: {str(e)}",
            "sources": []
        }