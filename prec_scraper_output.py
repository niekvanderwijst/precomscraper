import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
from playwright.sync_api import expect
import os


USERNAME = os.environ["PRECOM_USERNAME"]
PASSWORD = os.environ["PRECOM_PASSWORD"]

os.makedirs("public", exist_ok=True)

def read_occupancy_table(page) -> pd.DataFrame:
    page.wait_for_selector("#form_OccupancyProposalCounter")

    result = page.evaluate("""
        () => {
            const form = document.getElementById('form_OccupancyProposalCounter');

            const headerRow = form.querySelector('div.row');
            const columns = [...headerRow.querySelectorAll('.col label')]
                .map(l => l.innerText.trim());

            const userRows = [...form.querySelectorAll('div.row')]
                .filter(row => row.querySelector('.col-md-3 label'));

            const data = userRows.map(row => {
                const name = row.querySelector('.col-md-3 label').innerText.trim();
                const cols = [...row.querySelectorAll('.col:not(.col-md-3)')];

                const values = cols.map(col => {
                    const hiddenInput = col.querySelector('input[data-role="numerictextbox"]');
                    if (hiddenInput) {
                        const widget = jQuery('#' + hiddenInput.id).data('kendoNumericTextBox');
                        if (widget) return widget.value();
                        const raw = hiddenInput.getAttribute('aria-valuenow');
                        return raw !== null ? parseFloat(raw) : null;
                    }
                    return null;
                });

                return { name, values };
            });

            return { columns, data };
        }
    """)

    columns = result["columns"]
    rows = result["data"]

    data = []
    for row in rows:
        entry = {"Naam": row["name"]}
        for i, col in enumerate(columns):
            entry[col] = row["values"][i] if i < len(row["values"]) else None
        data.append(entry)

    return pd.DataFrame(data).set_index("Naam")


def export_to_html(df: pd.DataFrame, filepath: str = "index.html"):
    """Exporteer de bezettingsdata per rol als nette HTML-pagina."""

    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    timestamp = now.strftime("%d-%m-%Y %H:%M:%S %Z")

    # Bouw de rol-secties
    sections_html = ""
    for rol in df.columns:
        serie = df[rol].dropna().sort_values()

        if serie.empty:
            continue

        rows_html = ""
        for naam, waarde in serie.items():
            # Negatieve waarden krijgen een rode kleur, positief groen
            color_class = "positive" if waarde < 0 else "negative" if waarde > 0 else "neutral"
            rows_html += f"""
                <tr>
                    <td>{naam}</td>
                    <td class="{color_class}">{waarde:.2f}</td>
                </tr>"""

        sections_html += f"""
        <div class="rol-block">
            <h2>{rol}</h2>
            <table>
                <thead>
                    <tr>
                        <th>Naam</th>
                        <th>Waarde</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bezettingsvoorstel</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f4f6f9;
            color: #333;
            padding: 2rem;
        }}

        header {{
            margin-bottom: 2rem;
        }}

        header h1 {{
            font-size: 1.6rem;
            font-weight: 600;
            color: #1a1a2e;
        }}

        header p {{
            font-size: 0.85rem;
            color: #888;
            margin-top: 0.25rem;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }}

        .rol-block {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            overflow: hidden;
        }}

        .rol-block h2 {{
            background: #1a1a2e;
            color: #fff;
            font-size: 0.95rem;
            font-weight: 500;
            padding: 0.75rem 1rem;
            letter-spacing: 0.03em;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}

        thead tr {{
            background: #f0f2f5;
        }}

        th {{
            padding: 0.5rem 1rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.8rem;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        td {{
            padding: 0.55rem 1rem;
            border-top: 1px solid #f0f2f5;
        }}

        tr:hover td {{
            background: #fafbfc;
        }}

        td:last-child {{
            text-align: right;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }}

        .negative {{ color: #e53935; }}
        .positive {{ color: #43a047; }}
        .neutral  {{ color: #888; }}
    </style>
</head>
<body>
    <header>
        <h1>Bezettingsvoorstel</h1>
        <p>Gegenereerd op {timestamp}</p>
    </header>

    <div class="grid">
        {sections_html}
    </div>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Opgeslagen als {filepath}")

def print_per_rol(df: pd.DataFrame):
    """Print per rol een gesorteerde lijst van laag naar hoog, alleen gevulde waarden."""

    for rol in df.columns:
        serie = df[rol].dropna().sort_values()

        if serie.empty:
            continue

        print(f"\n{'='*40}")
        print(f"  {rol}")
        print(f"{'='*40}")
        for naam, waarde in serie.items():
            print(f"  {naam:<30} {waarde:>8.2f}")



with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Login
    page.goto("https://portal.pre-com.nl/PreCom/Account/Login")
    page.fill('input[type="text"]', USERNAME)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="button"]')
    page.wait_for_load_state("networkidle")

    print("Controleren of gebruiker is ingelogd...")

    # Navigeer naar bezettingsvoorstel
    page.get_by_text("Algemeen", exact=True).click()
    page.get_by_text("Bezettings voorstel", exact=True).click()
    page.wait_for_load_state("networkidle")

    page.locator("#form_OccupancyProposalCounter").wait_for()

    df = read_occupancy_table(page)
    print_per_rol(df)
    #export_to_html(df, "/Users/Niek/Sites/PrecomScraper/Public/index.html")
    export_to_html(df, "public/index.html")

    browser.close()
