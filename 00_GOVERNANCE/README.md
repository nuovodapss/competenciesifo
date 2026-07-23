# 00_GOVERNANCE

Inserire qui i file Excel/CSV contenenti le descrizioni delle singole competenze.

L'applicazione analizza automaticamente tutti i file e tutti i fogli presenti nella cartella, anche nelle sottocartelle. Il collegamento avviene:

1. per **Codice** della competenza;
2. in assenza del codice, per corrispondenza esatta del testo **Competenza**.

Sono riconosciute intestazioni come `Codice`, `Codice competenza`, `Descrizione`, `Descrizione competenza`, `Definizione`, `Descrittore` e `Comportamenti attesi`.

In alternativa, la cartella può essere indicata tramite la variabile d'ambiente `GOVERNANCE_DIR`.
