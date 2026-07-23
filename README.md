# APPGrade — Modifica e Download

Applicazione Streamlit semplificata per i coordinatori.

## Flusso operativo

1. Caricamento del file Excel di reparto scaricato dal Drive.
2. Selezione del professionista.
3. Modifica dei livelli direttamente nelle schede grafiche delle competenze.
4. Download del file Excel aggiornato.

La sezione di monitoraggio è stata rimossa. Le modifiche vengono conservate nella sessione dell'app e applicate automaticamente al file scaricato.

## Interfaccia

Le competenze sono organizzate in schede per dimensione, con:

- codice;
- titolo della competenza;
- descrizione della singola competenza;
- livello modificabile (`—`, `N`, `PAV`, `C`, `A`, `E`);
- punteggio della dimensione su 100.

## Descrizioni da `00_GOVERNANCE`

L'app ricerca automaticamente file `.xlsx`, `.xlsm`, `.xls` e `.csv` in:

- `00_GOVERNANCE/`
- `data/00_GOVERNANCE/`
- percorso indicato dalla variabile d'ambiente `GOVERNANCE_DIR`

Il matching avviene per codice della competenza o, come fallback, per titolo della competenza. Il caricatore tollera intestazioni differenti, ad esempio `Descrizione competenza`, `Definizione`, `Descrittore` o `Comportamenti attesi`.

## Avvio

```bash
pip install -r requirements.txt
streamlit run app.py
```

## File principali

- `app.py`: interfaccia semplificata Modifica + Download
- `data/guida_competenze.xlsx`: guida codici/dimensioni
- `00_GOVERNANCE/`: fonti delle descrizioni
- `config/structure_dimensions.yml`: mappa Struttura → Dimensioni
- `config/column_order.json`: ordine canonico delle colonne nel download
