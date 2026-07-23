# Gestione Competenze DAPSS — Coordinatori

Applicazione Streamlit per modificare i file Excel delle competenze senza collegamento diretto al Drive.

## Flusso operativo

1. Il coordinatore scarica dal Drive il file Excel della propria struttura.
2. Nell'header dell'app apre **Snapshot** e carica il file.
3. Seleziona struttura e professionista.
4. Nella scheda **Modifica** clicca il livello della singola competenza.
5. Nel pannello che si apre sceglie il livello e consulta:
   - descrittore Benner del livello selezionato;
   - definizione/razionale della competenza;
   - Attitudini, Motivazioni, Skills e Conoscenze del foglio `Descrittori`.
6. Preme **Salva modifiche**.
7. Nella scheda **Download** scarica il file aggiornato.
8. Ricarica manualmente il file sul Drive, sostituendo la versione precedente.

L'app non scrive direttamente sul Drive.

## Fonte Governance

La cartella `00_GOVERNANCE` è inclusa nell'app. I dati sono letti da:

- `02_Mappe/Mappa_Competenze_INF.xlsx`
  - foglio `Mappa` per competenze e definizioni;
  - foglio `Descrittori` per Attitudini, Motivazioni, Skills e Conoscenze;
  - foglio `Livelli Benner` per i descrittori dei livelli;
- `02_Mappe/Mappa_Strutture_Dimensioni_Competenza_INF.xlsx` per il perimetro delle dimensioni attive nella struttura.

## Avvio

```bash
pip install -r requirements.txt
streamlit run app.py
```
