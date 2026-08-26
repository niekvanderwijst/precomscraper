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


def build_voorstel_tabel(df: pd.DataFrame) -> str:
    """
    Bouw de voorgestelde bezetting tabel op basis van:
    - 1 Bevelvoerder  (laagste waarde)
    - 1 Chauffeur TS  (laagste waarde)
    - 1 Chauffeur WT  (laagste waarde)
    - 1 Manschap WT   (laagste waarde)
    - 4 Manschap      (laagste 4 waarden)
    Niemand wordt dubbel ingepland.
    """

    gekozen = set()
    rijen = []

    def kies_persoon(rol: str, aantal: int = 1):
        if rol not in df.columns:
            return []
        serie = df[rol].dropna().sort_values()
        resultaat = []
        for naam, waarde in serie.items():
            if naam not in gekozen:
                gekozen.add(naam)
                resultaat.append((naam, waarde))
                if len(resultaat) == aantal:
                    break
        return resultaat

    # Volgorde van toewijzing bepaalt prioriteit bij overlap
    taken = [
        ("Bevelvoerder",  "Bevelvoerder",  1),
        ("Chauffeur TS",  "Chauffeur TS",  1),
        ("Chauffeur WT",  "Chauffeur WT",  1),
        ("Manschap WT",   "Manschap WT",   1),
        ("Manschap",      "Manschap",      4),
    ]

    for label, rol, aantal in taken:
        personen = kies_persoon(rol, aantal)
        for i, (naam, waarde) in enumerate(personen):
            display_label = f"{label} {i + 1}" if aantal > 1 else label
            color_class = "positive" if waarde < 0 else "negative" if waarde > 0 else "neutral"
            rijen.append(f"""
                <tr>
                    <td><span class="badge">{display_label}</span></td>
                    <td>{naam}</td>
                    <td class="{color_class}">{waarde:.2f}</td>
                </tr>""")

    rows_html = "\n".join(rijen)

    return f"""
    <div class="voorstel-block">
        <h2>Voorgestelde Bezetting</h2>
        <table class="voorstel-table">
            <thead>
                <tr>
                    <th>Rol</th>
                    <th>Naam</th>
                    <th>Punten</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>"""


def export_to_html(df: pd.DataFrame, filepath: str = "index.html"):
    """Exporteer de bezettingsdata per rol als nette HTML-pagina."""

    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    timestamp = now.strftime("%d-%m-%Y %H:%M:%S %Z")

    # Bouw de voorstel sectie
    voorstel_html = build_voorstel_tabel(df)

    # Bouw de rol-secties
    sections_html = ""
    for rol in df.columns:
        serie = df[rol].dropna().sort_values()

        if serie.empty:
            continue

        block_id = rol.lower().replace(" ", "-")

        rows_html = ""
        for naam, waarde in serie.items():
            color_class = "positive" if waarde < 0 else "negative" if waarde > 0 else "neutral"
            rows_html += f"""
                <tr>
                    <td>{naam}</td>
                    <td class="{color_class}">{waarde:.2f}</td>
                </tr>"""

        sections_html += f"""
        <div class="rol-block" id="block-{block_id}">
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
            background: #0f1117;
            color: #e0e0e0;
            padding: 2rem;
        }}

        header {{
            margin-bottom: 2rem;
        }}

        header h1 {{
            font-size: 1.6rem;
            font-weight: 600;
            color: #ffffff;
        }}

        header p {{
            font-size: 0.85rem;
            color: #666;
            margin-top: 0.25rem;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }}

        .rol-block {{
            background: #1e2130;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.4);
            overflow: hidden;
            border: 1px solid #2a2d3e;
        }}

        .rol-block h2 {{
            background: #2a2d3e;
            color: #a0aec0;
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
            background: #181b27;
        }}

        th {{
            padding: 0.5rem 1rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.8rem;
            color: #4a5568;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        td {{
            padding: 0.55rem 1rem;
            border-top: 1px solid #2a2d3e;
            color: #cbd5e0;
        }}

        tr:hover td {{
            background: #252837;
        }}

        td:last-child {{
            text-align: right;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }}

        .negative {{ color: #fc8181; }}
        .positive {{ color: #68d391; }}
        .neutral  {{ color: #718096; }}

        /* Voorstel blok */
        .voorstel-block {{
            background: #1e2130;
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.5);
            overflow: hidden;
            border: 1px solid #3d4f7c;
            margin-bottom: 2rem;
        }}

        .voorstel-block h2 {{
            background: #2d3a5e;
            color: #90cdf4;
            font-size: 1rem;
            font-weight: 600;
            padding: 0.85rem 1rem;
            letter-spacing: 0.03em;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .voorstel-block h2::before {{
            content: "⚡";
        }}

        .voorstel-table td:first-child {{
            color: #90cdf4;
            font-weight: 500;
            width: 180px;
        }}

        .voorstel-table td:nth-child(2) {{
            color: #e2e8f0;
        }}

        .voorstel-table td:last-child {{
            text-align: right;
        }}

        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: #2d3a5e;
            color: #90cdf4;
        }}
    </style>
</head>
<body>
    <header>
        <h1>Bezettingsvoorstel</h1>
        <p>Gegenereerd op {timestamp}</p>
    </header>

    {voorstel_html}

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
    export_to_html(df, "public/index.html")

    browser.close()
