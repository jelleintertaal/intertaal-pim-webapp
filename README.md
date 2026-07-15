# Intertaal PIM — ISBN opzoektool

Simpele Streamlit-webapp voor Intertaal-medewerkers. Twee tabs:

- **Nielsen opzoeken** — Excel met ISBN's uploaden → verrijken via Nielsen BookData → downloaden in het vaste 141-koloms format.
- **CB opzoeken** — Excel met ISBN's uploaden → verrijken via CB Online (Algolia) inclusief druk (KB.nl) en cover-URL → downloaden in het vaste 16-koloms format.

## Live

Gehost op Streamlit Community Cloud. Vraag de URL en het gedeelde wachtwoord bij Jelle.

## Lokaal draaien

```
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Zet in `.env` of als omgevingsvariabelen:

```
APP_PASSWORD=<gedeeld wachtwoord>
NIELSEN_CLIENT_ID=...
NIELSEN_PASSWORD=...
CB_ALGOLIA_APP_ID=...
CB_ALGOLIA_API_KEY=...
CB_ALGOLIA_INDEX=...
```

## Bijhouden

- Codewijzigingen worden gemerged in `main` en Streamlit Cloud deployt automatisch.
- CB-sleutel verlopen? Zie [docs/runbook-cb-key.md](docs/runbook-cb-key.md).
- Nielsen dag-quotum (~1000/dag): al opgezochte ISBN's staan in de cache en tellen niet mee.
