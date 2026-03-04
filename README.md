# APPGrade — Applicativo Competenze (Streamlit · Reparto)

Web-app Streamlit per:
1) **Monitoraggio** delle competenze (per Struttura/Reparto)
2) **Modifica** dei livelli di competenza per singolo professionista, con calcolo immediato dei punteggi per **Dimensione**
3) **Download** del dataset in `.xlsx` con **struttura/ordine colonne uniforme** per l'accorpamento centrale

## Come funziona
- Il Coordinatore carica il **dataset di reparto** (xlsx).
- L'app legge la colonna `Struttura` e applica la mappa **Struttura → Dimensioni** (oltre alle Trasversali).
- Tab **Monitoraggio**: indicatori aggregati per Dimensione e ranking infermieri (score 0–100).
- Tab **Modifica & Download**: selezione infermiere, modifica livelli (`NA`, `N`, `Pav`, `C`, `A`, `E`), visualizzazione score per Dimensione (live), download del dataset aggiornato.

## Struttura del repository
- `app.py` : app Streamlit (single-page con 2 tab)
- `data/guida_competenze.xlsx` : **File Definitivo (Guida Competenze)** (mappa Dimensione ↔ Codici)
- `config/column_order.json` : ordine colonne canonico (base + Trasversali nell’ordine richiesto + tutte le altre competenze)
- `config/structure_dimensions.yml` : mappa `Struttura -> Dimensioni` (personalizzabile)
- `assets/style.css` : CSS minimale (sostituibile con lo stile dell'app Direzione)

## Avvio in locale
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy su Streamlit Community Cloud (via GitHub)
1. Crea un repository GitHub e carica questi file.
2. Su Streamlit Community Cloud collega il repository e imposta:
   - **Main file path**: `app.py`
   - **Python requirements**: `requirements.txt`

## Personalizzazione mappa Struttura->Dimensioni
Modifica `config/structure_dimensions.yml`.
- Se una Struttura non è presente, l'app mostra comunque le **Trasversali** e puoi selezionare manualmente le Dimensioni specifiche via UI.

## Nota sul download uniforme
- Il file scaricato contiene **tutti** i codici della guida in ordine canonico.
- I codici **non visibili** nella Struttura (fuori dallo scope) vengono impostati a `NA`.
