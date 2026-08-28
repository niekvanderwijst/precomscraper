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


def build_voorstel_data(df: pd.DataFrame) -> list:
    """
    Geeft een lijst van dicts terug met rol, naam en waarde voor de voorgestelde bezetting.
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

    taken = [
        ("Bevelvoerder", "Bevelvoerder", 1),
        ("Chauffeur TS",  "Chauffeur TS",  1),
        ("Chauffeur WT",  "Chauffeur WT",  1),
        ("Manschap WT",   "Manschap WT",   1),
        ("Manschap",      "Manschap",      4),
    ]

    for label, rol, aantal in taken:
        personen = kies_persoon(rol, aantal)
        for i, (naam, waarde) in enumerate(personen):
            display_label = f"{label} {i + 1}" if aantal > 1 else label
            rijen.append({
                "rol": display_label,
                "naam": naam,
                "waarde": waarde
            })

    return rijen


def build_alle_personen_per_rol(df: pd.DataFrame) -> dict:
    """
    Geeft per rol een gesorteerde lijst van (naam, waarde) terug voor de checkboxes.
    """
    result = {}
    for rol in df.columns:
        serie = df[rol].dropna().sort_values()
        if not serie.empty:
            result[rol] = [(naam, waarde) for naam, waarde in serie.items()]
    return result


def export_to_html(df: pd.DataFrame, filepath: str = "index.html"):
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    timestamp = now.strftime("%d-%m-%Y %H:%M:%S %Z")

    voorstel_data = build_voorstel_data(df)
    alle_personen = build_alle_personen_per_rol(df)

    # Bouw voorstel rijen als JSON voor JavaScript
    import json
    voorstel_json = json.dumps(voorstel_data)

    # Bouw checkboxes per rol
    checkboxes_html = ""
    for rol, personen in alle_personen.items():
        rol_id = rol.lower().replace(" ", "-")
        checkboxes_html += f"""
        <div class="rol-groep" id="checkgroup-{rol_id}">
            <h3>{rol}</h3>
            <div class="checkbox-lijst">"""
        for naam, waarde in personen:
            color_class = "positive" if waarde < 0 else "negative" if waarde > 0 else "neutral"
            naam_safe = naam.replace('"', '&quot;')
            checkboxes_html += f"""
                <label class="checkbox-item">
                    <input type="checkbox" class="beschikbaar-check"
                           data-naam="{naam_safe}"
                           data-rol="{rol}"
                           data-waarde="{waarde}">
                    <span class="check-naam">{naam}</span>
                    <span class="check-waarde {color_class}">{waarde:.2f}</span>
                </label>"""
        checkboxes_html += """
            </div>
        </div>"""

    # Bouw overzicht rijen html
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
                <thead><tr><th>Naam</th><th>Waarde</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bezettingsvoorstel</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f1117;
            color: #e0e0e0;
            padding: 2rem;
        }}

        header {{
            margin-bottom: 1.5rem;
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

        /* ── Tabs ── */
        .tabs {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            border-bottom: 2px solid #2a2d3e;
            padding-bottom: 0;
        }}

        .tab-btn {{
            background: none;
            border: none;
            border-bottom: 3px solid transparent;
            color: #718096;
            font-size: 0.95rem;
            font-weight: 500;
            padding: 0.6rem 1.2rem;
            cursor: pointer;
            transition: color 0.2s, border-color 0.2s;
            margin-bottom: -2px;
        }}

        .tab-btn:hover {{ color: #90cdf4; }}

        .tab-btn.active {{
            color: #90cdf4;
            border-bottom-color: #90cdf4;
        }}

        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}

        /* ── Voorstel tab ── */
        .voorstel-layout {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }}

        @media (max-width: 900px) {{
            .voorstel-layout {{ grid-template-columns: 1fr; }}
        }}

        /* Beschikbaarheid selectie */
        .beschikbaarheid-panel {{
            background: #1e2130;
            border-radius: 8px;
            border: 1px solid #2a2d3e;
            overflow: hidden;
        }}

        .beschikbaarheid-panel .panel-header {{
            background: #2a2d3e;
            padding: 0.85rem 1rem;
            font-size: 1rem;
            font-weight: 600;
            color: #a0aec0;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .beschikbaarheid-panel .panel-header::before {{ content: "✅"; }}

        .beschikbaarheid-body {{
            padding: 1rem;
            max-height: 520px;
            overflow-y: auto;
        }}

        .rol-groep {{
            margin-bottom: 1.2rem;
        }}

        .rol-groep h3 {{
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #4a5568;
            margin-bottom: 0.5rem;
            padding-bottom: 0.3rem;
            border-bottom: 1px solid #2a2d3e;
        }}

        .checkbox-lijst {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }}

        .checkbox-item {{
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.4rem 0.5rem;
            border-radius: 5px;
            cursor: pointer;
            transition: background 0.15s;
        }}

        .checkbox-item:hover {{ background: #252837; }}

        .checkbox-item input[type="checkbox"] {{
            width: 15px;
            height: 15px;
            accent-color: #90cdf4;
            cursor: pointer;
            flex-shrink: 0;
        }}

        .check-naam {{
            flex: 1;
            font-size: 0.9rem;
            color: #cbd5e0;
        }}

        .check-waarde {{
            font-size: 0.85rem;
            font-weight: 500;
            font-variant-numeric: tabular-nums;
            min-width: 48px;
            text-align: right;
        }}

        /* Acties */
        .voorstel-acties {{
            display: flex;
            gap: 0.75rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}

        .btn {{
            padding: 0.5rem 1.1rem;
            border-radius: 6px;
            border: none;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }}

        .btn:hover {{ opacity: 0.85; }}

        .btn-primary {{
            background: #2d3a5e;
            color: #90cdf4;
            border: 1px solid #3d4f7c;
        }}

        .btn-secondary {{
            background: #252837;
            color: #a0aec0;
            border: 1px solid #2a2d3e;
        }}

        /* Voorstel resultaat */
        .voorstel-resultaat {{
            background: #1e2130;
            border-radius: 8px;
            border: 1px solid #3d4f7c;
            overflow: hidden;
        }}

        .voorstel-resultaat .panel-header {{
            background: #2d3a5e;
            padding: 0.85rem 1rem;
            font-size: 1rem;
            font-weight: 600;
            color: #90cdf4;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .voorstel-resultaat .panel-header::before {{ content: "⚡"; }}

        .voorstel-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}

        .voorstel-table thead tr {{ background: #181b27; }}

        .voorstel-table th {{
            padding: 0.5rem 1rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.8rem;
            color: #4a5568;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .voorstel-table td {{
            padding: 0.55rem 1rem;
            border-top: 1px solid #2a2d3e;
            color: #cbd5e0;
        }}

        .voorstel-table tr:hover td {{ background: #252837; }}

        .voorstel-table td:last-child {{
            text-align: right;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }}

        .voorstel-table td:first-child {{ color: #90cdf4; width: 180px; }}

        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            background: #2d3a5e;
            color: #90cdf4;
        }}

        .badge.vervangen {{
            background: #3a2d2d;
            color: #fc8181;
        }}

        .onbeschikbaar td {{
            opacity: 0.4;
            text-decoration: line-through;
        }}

        .voorstel-leeg {{
            padding: 1.5rem 1rem;
            color: #4a5568;
            font-size: 0.9rem;
            text-align: center;
        }}

        /* ── Overzicht tab ── */
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

        thead tr {{ background: #181b27; }}

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

        tr:hover td {{ background: #252837; }}

        td:last-child {{
            text-align: right;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }}

        .negative {{ color: #fc8181; }}
        .positive {{ color: #68d391; }}
        .neutral  {{ color: #718096; }}

        /* Scrollbar styling */
        .beschikbaarheid-body::-webkit-scrollbar {{ width: 6px; }}
        .beschikbaarheid-body::-webkit-scrollbar-track {{ background: #1e2130; }}
        .beschikbaarheid-body::-webkit-scrollbar-thumb {{ background: #2a2d3e; border-radius: 3px; }}
    </style>
</head>
<body>
    <header>
        <h1>Bezettingsvoorstel</h1>
        <p>Gegenereerd op {timestamp}</p>
    </header>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('voorstel', this)">⚡ Voorgestelde Bezetting</button>
        <button class="tab-btn" onclick="switchTab('overzicht', this)">📋 Overzicht per Rol</button>
    </div>

    <!-- TAB 1: Voorgestelde Bezetting -->
    <div class="tab-panel active" id="tab-voorstel">
        <div class="voorstel-acties">
            <button class="btn btn-primary" onclick="herbereken()">🔄 Herbereken voorstel</button>
            <button class="btn btn-secondary" onclick="alleDeselecteren()">✖ Alles deselecteren</button>
        </div>

        <div class="voorstel-layout">
            <!-- Links: beschikbaarheid aanvinken -->
            <div class="beschikbaarheid-panel">
                <div class="panel-header">Beschikbaarheid</div>
                <div class="beschikbaarheid-body">
                    {checkboxes_html}
                </div>
            </div>

            <!-- Rechts: voorstel resultaat -->
            <div class="voorstel-resultaat">
                <div class="panel-header">Voorstel</div>
                <div id="voorstel-output">
                    <table class="voorstel-table" id="voorstel-tabel">
                        <thead>
                            <tr>
                                <th>Rol</th>
                                <th>Naam</th>
                                <th>Punten</th>
                            </tr>
                        </thead>
                        <tbody id="voorstel-body"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- TAB 2: Overzicht per Rol -->
    <div class="tab-panel" id="tab-overzicht">
        <div class="grid">
            {sections_html}
        </div>
    </div>

    <script>
        // Originele data vanuit Python
        const origineelVoorstel = {voorstel_json};

        // Alle personen per rol vanuit checkboxes
        function getBeschikbarePersonen() {{
            const beschikbaar = {{}};
            document.querySelectorAll('.beschikbaar-check').forEach(cb => {{
                const rol = cb.dataset.rol;
                if (!beschikbaar[rol]) beschikbaar[rol] = [];
                if (cb.checked) {{
                    beschikbaar[rol].push({{
                        naam: cb.dataset.naam,
                        waarde: parseFloat(cb.dataset.waarde)
                    }});
                }}
            }});
            return beschikbaar;
        }}

        function switchTab(tabId, btn) {{
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            btn.classList.add('active');
        }}

        function alleDeselecteren() {{
            document.querySelectorAll('.beschikbaar-check').forEach(cb => cb.checked = false);
            herbereken();
        }}

        function herbereken() {{
            const beschikbaar = getBeschikbarePersonen();
            const gekozen = new Set();
            const tbody = document.getElementById('voorstel-body');
            tbody.innerHTML = '';

            const taken = [
                {{ label: 'Bevelvoerder', rol: 'Bevelvoerder', aantal: 1 }},
                {{ label: 'Chauffeur TS',  rol: 'Chauffeur TS',  aantal: 1 }},
                {{ label: 'Chauffeur WT',  rol: 'Chauffeur WT',  aantal: 1 }},
                {{ label: 'Manschap WT',   rol: 'Manschap WT',   aantal: 1 }},
                {{ label: 'Manschap',      rol: 'Manschap',      aantal: 4 }},
            ];

            taken.forEach(taak => {{
                const kandidaten = (beschikbaar[taak.rol] || [])
                    .filter(p => !gekozen.has(p.naam))
                    .sort((a, b) => a.waarde - b.waarde);

                const slots = taak.aantal;
                for (let i = 0; i < slots; i++) {{
                    const displayLabel = slots > 1 ? `${{taak.label}} ${{i + 1}}` : taak.label;
                    if (i < kandidaten.length) {{
                        const p = kandidaten[i];
                        gekozen.add(p.naam);
                        const colorClass = p.waarde < 0 ? 'positive' : p.waarde > 0 ? 'negative' : 'neutral';
                        tbody.innerHTML += `
                            <tr>
                                <td><span class="badge">${{displayLabel}}</span></td>
                                <td>${{p.naam}}</td>
                                <td class="${{colorClass}}">${{p.waarde.toFixed(2)}}</td>
                            </tr>`;
                    }} else {{
                        tbody.innerHTML += `
                            <tr>
                                <td><span class="badge vervangen">${{displayLabel}}</span></td>
                                <td style="color:#4a5568;font-style:italic;">— niet beschikbaar —</td>
                                <td></td>
                            </tr>`;
                    }}
                }}
            }});

            if (tbody.innerHTML === '') {{
                tbody.innerHTML = '<tr><td colspan="3" class="voorstel-leeg">Vink personen aan om een voorstel te genereren.</td></tr>';
            }}
        }}

        // Init: toon standaard voorstel op basis van originele data
        (function initVoorstel() {{
            // Zet de checkboxes aan voor mensen in het originele voorstel
            const voorgesteldeNamen = new Set(origineelVoorstel.map(r => r.naam));
            document.querySelectorAll('.beschikbaar-check').forEach(cb => {{
                if (voorgesteldeNamen.has(cb.dataset.naam)) {{
                    cb.checked = true;
                }}
            }});

            herbereken();
        }})();
    </script>
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Opgeslagen als {filepath}")


def print_per_rol(df: pd.DataFrame):
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

    page.goto("https://portal.pre-com.nl/PreCom/Account/Login")
    page.fill('input[type="text"]', USERNAME)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="button"]')
    page.wait_for_load_state("networkidle")

    print("Controleren of gebruiker is ingelogd...")

    page.get_by_text("Algemeen", exact=True).click()
    page.get_by_text("Bezettings voorstel", exact=True).click()
    page.wait_for_load_state("networkidle")

    page.locator("#form_OccupancyProposalCounter").wait_for()

    df = read_occupancy_table(page)
    print_per_rol(df)
    export_to_html(df, "public/index.html")

    browser.close()
