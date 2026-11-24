import re
import tldextract
import csv

from pathlib import Path
from html import unescape
from urllib.parse import urlsplit

extract_domain = tldextract.TLDExtract(suffix_list_urls=())


def get_company(url):
    hostname = urlsplit(url).hostname

    if not hostname:
        return ""

    return extract_domain(hostname).domain


EMAIL_RE = re.compile(
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.IGNORECASE
)


def extract_emails(content):
    return set(EMAIL_RE.findall(unescape(content)))


def export_contacts(contacts, output_path):

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    seen = set()

    with output.open("w", newline="", encoding="utf-8") as file:

        writer = csv.writer(file)

        writer.writerow([
            "company",
            "email",
            "source_url",
            "sector",
            "city",
            "website",
            "notes"
        ])

        for rank, company, email, source_url, website in contacts:

            key = (company, email.casefold())

            if key in seen:
                continue

            seen.add(key)

            writer.writerow([
                company,
                email,
                source_url,
                "",
                "",
                website,
                ""
            ])

    print(f"[OK] {len(seen)} contacts exported to {output}")




