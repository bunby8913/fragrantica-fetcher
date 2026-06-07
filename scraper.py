#!/usr/bin/env python3
"""
Fragrantica Perfume Scraper

Fetches a single fragrantica.com perfume page, extracts perfume data, and
outputs tab-separated text that can be copied directly into Excel.

Usage:
    python scraper.py <url>
    python scraper.py https://www.fragrantica.com/perfume/Chanel/Coco-Mademoiselle-549.html
"""

import re
import sys
import argparse
import curl_cffi.requests as requests
from bs4 import BeautifulSoup


def fetch_page(url: str) -> str:
    """Fetch HTML content from a fragrantica perfume URL via curl_cffi."""
    resp = requests.get(url, impersonate="chrome120", timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_perfume_data(html: str, url: str) -> dict:
    """Extract all perfume data from the HTML."""
    soup = BeautifulSoup(html, "lxml")

    name = _extract_name(soup)
    brand = _extract_brand(soup)
    perfumer = _extract_perfumer(soup)
    description = _extract_description(soup)
    rating_value = _extract_rating_value(soup)
    rating_count = _extract_rating_count(soup)
    accords = _extract_accords(soup)
    pyramid = _extract_pyramid(soup)
    perfume_id = _extract_id(url)

    return {
        "id": perfume_id,
        "name": name,
        "brand": brand,
        "perfumer": perfumer,
        "description": description,
        "rating_value": rating_value,
        "rating_count": rating_count,
        "main_accords": accords,
        "pyramid": pyramid,
        "source_url": url,
    }


def _extract_name(soup: BeautifulSoup) -> str:
    el = soup.select_one('h1[itemprop="name"]')
    if not el:
        return ""
    full = el.get_text(" ", strip=True)
    span = el.select_one("span")
    if span:
        full = full.replace(span.get_text(strip=True), "").strip()
    return full


def _extract_brand(soup: BeautifulSoup) -> str:
    el = soup.select_one('[itemprop="brand"] [itemprop="name"]')
    return el.get_text(strip=True) if el else ""


def _extract_perfumer(soup: BeautifulSoup) -> str:
    desc_el = soup.select_one('[itemprop="description"] p')
    if desc_el:
        text = desc_el.get_text(strip=True)
        m = re.search(
            r"(?:nose behind this fragrance is|created by)\s+(.*?)(?:\.|$)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()

    heading = soup.find("h3", string=re.compile(r"Perfumer", re.I))
    if heading:
        parent = heading.find_parent("div")
        if parent:
            spans = parent.select("a span")
            if spans:
                return ", ".join(s.get_text(strip=True) for s in spans)
    return ""


def _extract_description(soup: BeautifulSoup) -> str:
    el = soup.select_one('[itemprop="description"]')
    if not el:
        return ""
    for tag in el.select("script, style"):
        tag.decompose()
    return str(el)


def _extract_rating_value(soup: BeautifulSoup) -> str:
    el = soup.select_one('[itemprop="ratingValue"]')
    return el.get_text(strip=True) if el else ""


def _extract_rating_count(soup: BeautifulSoup) -> str:
    el = soup.select_one('[itemprop="ratingCount"]')
    if not el:
        return ""
    return el.get("content", el.get_text(strip=True))


def _extract_accords(soup: BeautifulSoup) -> list:
    """Extract main accords: name, width_pct, opacity, background color, text color."""
    accords = []
    heading = soup.find("h6", string=re.compile(r"main accords", re.I))
    if not heading:
        return accords

    container = heading.parent
    if not container:
        return accords

    bars = container.select('div[style*="width:"][style*="background:"]')
    for bar in bars:
        style = bar.get("style", "")
        span = bar.select_one("span.truncate")
        if not span:
            continue

        name = span.get_text(strip=True)

        width_match = re.search(r"width:\s*([\d.]+)%", style)
        width_pct = float(width_match.group(1)) if width_match else 0

        opacity_match = re.search(r"opacity:\s*([\d.]+)%", style)
        opacity = float(opacity_match.group(1)) / 100.0 if opacity_match else 1.0

        bg_match = re.search(r"background:\s*(#[0-9a-fA-F]+)", style)
        bg_color = bg_match.group(1) if bg_match else "#ccc"

        color_match = re.search(r"color:\s*(#[0-9a-fA-F]+)", style)
        text_color = color_match.group(1) if color_match else "#000"

        accords.append(
            {
                "name": name,
                "width_pct": round(width_pct, 2),
                "opacity": round(opacity, 4),
                "background": bg_color,
                "text_color": text_color,
            }
        )

    return accords


def _extract_pyramid(soup: BeautifulSoup) -> dict:
    """Extract perfume pyramid with top/middle/base notes grouped by container."""
    pyramid = {"top_notes": [], "middle_notes": [], "base_notes": []}

    pyramid_section = soup.select_one("#pyramid")
    if not pyramid_section:
        return pyramid

    all_level_containers = pyramid_section.select("pyramid-level-new")
    for container in all_level_containers:
        notes_attr = container.get("notes", "").lower()
        if notes_attr == "top":
            level_key = "top_notes"
        elif notes_attr == "middle":
            level_key = "middle_notes"
        elif notes_attr == "base":
            level_key = "base_notes"
        else:
            continue

        for link in container.select("a.pyramid-note-link"):
            note = _parse_note_link(link)
            if note:
                pyramid[level_key].append(note)

    return pyramid


def _parse_note_link(note_link) -> dict | None:
    href = note_link.get("href", "")
    style = note_link.get("style", "")

    img = note_link.select_one("img")
    img_src = img.get("src", "") if img else ""
    img_alt = img.get("alt", "") if img else ""

    label = note_link.select_one("span.pyramid-note-label")
    note_name = label.get_text(strip=True) if label else img_alt

    note_id = ""
    if href:
        id_match = re.search(r"-(\d+)\.html$", href)
        note_id = id_match.group(1) if id_match else ""

    opacity_match = re.search(r"opacity:\s*([\d.]+)", style)
    opacity = float(opacity_match.group(1)) if opacity_match else 1.0

    return {
        "name": note_name,
        "note_id": note_id,
        "image_url": img_src,
        "opacity": round(opacity, 4),
    }


def _extract_id(url: str) -> str:
    match = re.search(r"-(\d+)\.html$", url)
    return match.group(1) if match else ""


def format_pyramid_text(pyramid: dict) -> str:
    """Format pyramid data as a single text line grouped by level."""
    parts = []
    for level_key, level_label in [
        ("top_notes", "Top"),
        ("middle_notes", "Middle"),
        ("base_notes", "Base"),
    ]:
        notes = pyramid.get(level_key, [])
        if notes:
            note_names = ", ".join(n["name"] for n in notes)
            parts.append(f"{level_label}: {note_names}")
    return "; ".join(parts)


def format_output_line(data: dict) -> str:
    """Format perfume data as a tab-separated line for Excel copy-paste."""
    name = data["name"]
    brand = data["brand"]
    pyramid = format_pyramid_text(data["pyramid"])
    return f"{name}\t{brand}\t{pyramid}"


def main():
    parser = argparse.ArgumentParser(
        description="Scrape a fragrantica.com perfume page and output tab-separated text."
    )
    parser.add_argument(
        "url",
        help="Full URL of the fragrantica perfume page",
    )
    args = parser.parse_args()

    url = args.url.strip()
    if "fragrantica.com/perfume/" not in url:
        print("Error: URL must be a fragrantica.com perfume page", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching: {url}", file=sys.stderr)
    html = fetch_page(url)

    print("Parsing perfume data...", file=sys.stderr)
    data = extract_perfume_data(html, url)

    if not data["name"]:
        print("Error: could not extract perfume name", file=sys.stderr)
        sys.exit(1)

    print(f"Name\tBrand\tPyramid")
    print(format_output_line(data))

    print(f"\nDone! {data['name']} by {data['brand']}", file=sys.stderr)
    print(f"  Accords: {len(data['main_accords'])}", file=sys.stderr)
    print(
        f"  Pyramid: "
        f"{len(data['pyramid']['top_notes'])}T / "
        f"{len(data['pyramid']['middle_notes'])}M / "
        f"{len(data['pyramid']['base_notes'])}B",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
