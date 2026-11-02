"""Brand / competitor flags per answer and a per-platform summary."""
import re
from collections import defaultdict


def _matches(domain, targets):
    return next((t for t in targets if domain == t or domain.endswith("." + t)), "")


def _label(domain):
    """'zeelool.com' -> 'zeelool' (used as the mention term for competitors)."""
    return domain.split(".")[0]


def _mentioned(text, terms):
    return [t for t in terms if t and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I)]


def score(answers, citations, s):
    brand_domains, comp_domains = s["brand_domains"], s["competitor_domains"]
    brand_terms = s["brand_terms"] or [_label(d) for d in brand_domains]
    comp_terms = {d: _label(d) for d in comp_domains}

    by_key = defaultdict(list)
    for c in citations:
        c["is_brand"] = bool(_matches(c["domain"], brand_domains))
        c["competitor"] = _matches(c["domain"], comp_domains)
        by_key[(c["platform"], c["query"])].append(c)

    for a in answers:
        cs = by_key[(a["platform"], a["query"])]
        brand_pos = [int(c["position"]) for c in cs if c["is_brand"] and str(c["position"]).isdigit()]
        has_text = bool(a["response_text"])
        a["n_citations"] = len(cs)
        a["brand_cited"] = bool(brand_pos)
        a["brand_best_position"] = min(brand_pos) if brand_pos else ""
        a["brand_mentioned"] = bool(_mentioned(a["response_text"], brand_terms)) if has_text else ""
        a["competitors_cited"] = ";".join(sorted({c["competitor"] for c in cs if c["competitor"]}))
        a["competitors_mentioned"] = ";".join(sorted(
            d for d, term in comp_terms.items() if has_text and _mentioned(a["response_text"], [term])))
    return answers, citations


def summarize(answers, s):
    """One row per platform: answer rate and brand vs competitor visibility."""
    rows = []
    platforms = sorted({a["platform"] for a in answers})
    for p in platforms:
        rs = [a for a in answers if a["platform"] == p]
        ok = [a for a in rs if a["status"] == "ok"]
        n = len(ok) or 1
        row = {
            "platform": p,
            "queries": len(rs),
            "answered": len(ok),
            "no_ai_answer": sum(a["status"] == "no_ai_answer" for a in rs),
            "errors_or_timeouts": sum(a["status"] in ("error", "timeout") for a in rs),
            "brand_cited_pct": round(100 * sum(a["brand_cited"] is True for a in ok) / n, 1),
            "brand_mentioned_pct": (round(100 * sum(a["brand_mentioned"] is True for a in ok) / n, 1)
                                    if any(a["response_text"] for a in ok) else ""),
        }
        for d in s["competitor_domains"]:
            row[f"{d}_cited_pct"] = round(100 * sum(d in a["competitors_cited"].split(";") for a in ok) / n, 1)
        rows.append(row)
    return rows
