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
from urllib.parse import urljoin
import curl_cffi.requests as requests
from bs4 import BeautifulSoup


FRAGRANTICA_BASE = "https://www.fragrantica.com"


def fetch_page(url: str) -> str:
    """Fetch HTML content from a fragrantica URL via curl_cffi."""
    resp = requests.get(url, impersonate="chrome120", timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_perfume_data(html: str, url: str) -> dict:
    """Extract all perfume data from the HTML."""
    soup = BeautifulSoup(html, "lxml")

    brand = _extract_brand(soup)
    name = _extract_name(soup, brand)
    rating_value = _extract_rating_value(soup)
    rating_count = _extract_rating_count(soup)
    accords = _extract_accords(soup)
    pyramid = _extract_pyramid(soup)
    perfume_id = _extract_id(url)

    return {
        "id": perfume_id,
        "name": name,
        "brand": brand,
        "rating_value": rating_value,
        "rating_count": rating_count,
        "main_accords": accords,
        "pyramid": pyramid,
        "source_url": url,
    }


def _extract_name(soup: BeautifulSoup, brand: str = "") -> str:
    el = soup.select_one('h1[itemprop="name"]')
    if not el:
        return ""
    full = el.get_text(" ", strip=True)
    span = el.select_one("span")
    if span:
        full = full.replace(span.get_text(strip=True), "").strip()
    if brand:
        full = re.sub(re.escape(brand), "", full, flags=re.IGNORECASE).strip()
    full = re.sub(r"\s+", " ", full)
    return full


def _extract_brand(soup: BeautifulSoup) -> str:
    el = soup.select_one('[itemprop="brand"] [itemprop="name"]')
    return el.get_text(strip=True) if el else ""


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

    if any(pyramid.values()):
        return pyramid

    fallback_containers = []
    for container in all_level_containers:
        notes = []
        image_areas = []
        for link in container.select("a.pyramid-note-link"):
            note = _parse_note_link(link)
            if not note:
                continue
            notes.append(note)
            image_areas.append(_note_image_area(note))

        if notes:
            average_area = sum(image_areas) / len(image_areas) if image_areas else 0
            fallback_containers.append({"notes": notes, "average_area": average_area})

    if not fallback_containers:
        return pyramid

    fallback_containers.sort(key=lambda item: item["average_area"], reverse=True)
    if len(fallback_containers) == 1:
        pyramid["top_notes"].extend(fallback_containers[0]["notes"])
    elif len(fallback_containers) == 2:
        pyramid["top_notes"].extend(fallback_containers[0]["notes"])
        pyramid["base_notes"].extend(fallback_containers[1]["notes"])
    else:
        pyramid["top_notes"].extend(fallback_containers[0]["notes"])
        pyramid["base_notes"].extend(fallback_containers[-1]["notes"])
        for container in fallback_containers[1:-1]:
            pyramid["middle_notes"].extend(container["notes"])

    return pyramid


def _parse_note_link(note_link) -> dict | None:
    href = note_link.get("href", "")
    style = note_link.get("style", "")

    img = note_link.select_one("img")
    img_src = img.get("src", "") if img else ""
    img_alt = img.get("alt", "") if img else ""
    img_width, img_height = _parse_image_dimensions(img)

    label = note_link.select_one("span.pyramid-note-label")
    note_name = label.get_text(strip=True) if label else img_alt

    note_id = ""
    if href:
        id_match = re.search(r"-(\d+)\.html$", href)
        note_id = id_match.group(1) if id_match else ""

    note_url = urljoin(FRAGRANTICA_BASE, href) if href else ""

    opacity_match = re.search(r"opacity:\s*([\d.]+)", style)
    opacity = float(opacity_match.group(1)) if opacity_match else 1.0

    return {
        "name": note_name,
        "note_id": note_id,
        "note_url": note_url,
        "image_url": img_src,
        "image_width": img_width,
        "image_height": img_height,
        "opacity": round(opacity, 4),
    }


def extract_note_odor_profile(html: str) -> str:
    """Parse a fragrantica note page and return the odor profile text.

    Returns an empty string if no odor profile is present. The text is
    whitespace-normalized (newlines/tabs collapsed to single spaces,
    ends stripped). Only the description directly following the
    literal ``Odor profile:`` label is captured; the parse stops at
    the first occurrence of the ``Most popular perfumes`` section
    boundary, or at the ``Total Agreement`` label, or at the end of
    the document.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)

    match = re.search(
        r"Odor profile:\s*(.*?)(?:\n\s*Most popular perfumes|\n\s*Total Agreement|\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        return ""

    profile = match.group(1)
    profile = re.sub(r"\s+", " ", profile).strip()
    return profile


def _parse_image_dimensions(img) -> tuple[float, float]:
    if not img:
        return 0, 0

    width = _parse_numeric_dimension(img.get("width", ""))
    height = _parse_numeric_dimension(img.get("height", ""))

    style = img.get("style", "")
    if not width:
        width_match = re.search(r"width:\s*([\d.]+)px", style)
        width = float(width_match.group(1)) if width_match else 0
    if not height:
        height_match = re.search(r"height:\s*([\d.]+)px", style)
        height = float(height_match.group(1)) if height_match else 0

    if not width or not height:
        srcset_size = _largest_srcset_width(img.get("srcset", ""))
        width = width or srcset_size
        height = height or srcset_size

    return width, height


def _parse_numeric_dimension(value: str) -> float:
    match = re.search(r"[\d.]+", str(value))
    return float(match.group(0)) if match else 0


def _largest_srcset_width(srcset: str) -> float:
    widths = [float(width) for width in re.findall(r"\s(\d+(?:\.\d+)?)w", srcset)]
    return max(widths) if widths else 0


def _note_image_area(note: dict) -> float:
    width = float(note.get("image_width") or 0)
    height = float(note.get("image_height") or 0)
    if width and height:
        return width * height
    return width or height


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
