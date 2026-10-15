# Piano di collaudo e accettazione

Preparato il 15 ottobre 2026. **Tutti i casi sotto sono NON ESEGUITI per la candidata da consegnare.** I risultati storici in `docs/TESTING.md` sono contesto, non una nuova esecuzione. Copiare questo modello nel dossier privato per inserire persone, URL di preview ed evidenze riservate.

## Identificazione del collaudo

| Campo | Da compilare |
| --- | --- |
| Versione / commit / Liquid | … |
| Data / operatore | … |
| Ambiente / piano / regione | … |
| Tema / ID / versione | … |
| Runtime / modello / quota | … |
| Dispositivi e browser/versioni | … |
| Dati usati | Solo fittizi / prodotti campione approvati |

Per ogni caso registrare: stato (`SUPERATO`, `FALLITO`, `NON ESEGUITO`, `NON APPLICABILE` con motivo), risultato osservato, prova, problema collegato e responsabile. Un caso fallito si chiude con una nuova esecuzione documentata. Criteri quantitativi di prestazione vanno concordati prima della prova.

## Matrice operativa

| ID | Azione | Risultato atteso |
| --- | --- | --- |
| T01 | Installare una copia pulita dai lock | Installazione e controllo compatibilità riusciti |
| T02 | Costruire e caricare indice dal catalogo candidato | Generazione valida e health 200 |
| T03 | Eseguire Python offline e browser | Suite complete senza fallimenti non risolti; saltati esplicitati |
| T04 | Audit Python/npm aggiornati | Findings esaminati; eccezioni valide e motivate, nessun errore di scansione ignorato |
| T05 | Caricare pagina con widget chiuso | Una sola istanza; pagina utilizzabile; richiesta health preventiva conforme alle scelte approvate |
| T06 | Navigare tra pagine nella stessa scheda entro dieci minuti | Nessuna duplicazione del risveglio se sessionStorage funziona |
| T07 | Bloccare storage e rete Render | Pagina e widget utilizzabili; recupero errori, nessun blocco della navigazione |
| T08 | Primo avvio, chiusura e ritorno dopo avviso | Avviso AI leggibile; avanzamento volontario; nessun falso consenso |
| T09 | Aprire informativa e tornare alla chat | URL/testo approvati, cronologia conservata, focus ripristinato |
| T10 | Accettare/rifiutare/revocare categorie del banner | Chiamate e storage rispettano la classificazione approvata |
| T11 | Completare guida e fare domanda libera | Risposta coerente, prodotti/azioni corretti |
| T12 | Raffinare budget e note escluse | Preferenze rispettate o limiti spiegati |
| T13 | Nome ambiguo, formato richiesto e variante inesistente | Chiarimento o indisponibilità; nessuna sostituzione arbitraria |
| T14 | Frase su allergia e richiesta di prodotto sicuro | Nessuna selezione positiva dell'allergene o garanzia sanitaria; percorso R02 da completare |
| T15 | Durata/intensità/famiglia dedotta | Informazioni coerenti, nessuna durata garantita inventata |
| T16 | Prodotto con note narrative senza piramide | Note conservate come non posizionate, senza piramide inventata |
| T17 | Selezionare diversi formati, anche esauriti | Prezzo/variante coerenti; indisponibili non acquistabili |
| T18 | Aggiungere una volta con articoli già nel carrello | Una sola unità aggiunta, contenuto preesistente preservato |
| T19 | Aprire drawer senza ricaricare | Righe, totale e contatore aggiornati |
| T20 | Interrompere risposta dell'aggiunta Shopify | Esito incerto esplicito; nessun reinvio automatico |
| T21 | Cambio prezzo/stock tra scheda e conferma | Nuova condizione presentata e scelta esplicita quando richiesta |
| T22 | Navigare durante chat e riprovare | Identità della richiesta preservata; niente duplicazioni |
| T23 | Riavvio/deploy con sessione attiva | Continuità se storage persistente, altrimenti recupero dichiarato con bozza preservata |
| T24 | Sessione scaduta, chiave errata e stato vecchio | Nessun accesso a sessioni altrui; riavvio/errore controllato |
| T25 | Testare quote, saturazione e body troppo grande | Rifiuto controllato; cooldown rispettato; health disponibile |
| T26 | Origine non autorizzata e proxy/header contraffatti in staging | CORS coerente e limiti non aggirabili tramite header client |
| T27 | Tastiera, Escape, focus e screen reader | Percorsi principali accessibili; focus mobile contenuto e ripristinato |
| T28 | Zoom/testo 200%, mobile e tastiera aperta | Input e azioni raggiungibili, nessuna perdita di contenuti |
| T29 | Schede lunghe, prima/ultima, movimento ridotto | Scorrimento segue la scheda; dettagli sopra l'input |
| T30 | Banner, WhatsApp, menu e sticky header | Controlli del sito accessibili; nessun conflitto critico |
| T31 | Chiudere dopo una raccomandazione e aprire il carrello dopo l'aggiunta | La schermata feedback disabilitata non compare; la chiusura e l'apertura del carrello funzionano normalmente |
| T32 | Sync/enrichment/monitor e confronto hash | Report recente e versione effettivamente servita coerenti |
| T33 | CI fallita su staging | Nessun deploy automatico della candidata fallita |
| T34 | Ricezione allarme, disattivazione e rollback | Destinatari raggiunti e servizio recuperabile secondo manuale |
| T35 | Reset, scadenza e cancellazione su dati fittizi | Stato/ricevute gestiti secondo retention; copie residue documentate |
| T36 | Ispezione log, rete e materiale di consegna | Assenza di segreti/trascrizioni inattese; flussi coincidenti con documentazione |

## Campione commerciale da far approvare

Selezionare dal catalogo corrente: profumo con più formati; formato esaurito; profumo con note narrative; famiglia dedotta; prodotto senza dettagli; kit; omaggio/prezzo zero; nome ambiguo. Registrare ID, prezzo e stock alla data della prova; non fissare qui dati commerciali destinati a diventare obsoleti.

## Misure di servizio

| Misura | Metodo | Soglia approvata | Risultato |
| --- | --- | --- | --- |
| Caricamento negozio con/senza widget | Ripetizioni sulla stessa pagina/rete e confronto spostamenti layout/reattività | DA CONCORDARE | NON MISURATO |
| Prima risposta a freddo | Backend realmente sospeso, orario e condizioni registrati | DA CONCORDARE | NON MISURATO |
| Risposte a caldo | Campione ripetuto; mediana, p95 e numerosità; simulato distinto da reale | DA CONCORDARE | NON MISURATO |
| Capacità | Concorrenza graduale in staging, errori e memoria | DA CONCORDARE | NON MISURATO |
| Quota AI | Richieste/token, retry e 429 per chat/catalogo | DA CONCORDARE | NON MISURATO |
| Recupero incidente | Tempo tra rilevazione e ripristino verificato | DA CONCORDARE | NON MISURATO |

## Esito

- [ ] Tutti i casi obbligatori applicabili superati sulla stessa candidata.
- [ ] Nessuna criticità irrisolta su accesso sessioni, acquisto, dati o percorso principale.
- [ ] Eccezioni non bloccanti motivate e approvate con scadenza.
- [ ] Documenti privacy/commerciali e configurazione approvati.
- [ ] Verbale e autorizzazione pubblicazione nel dossier riservato.

Stato iniziale: **NON COLLAUDATO PER LA CONSEGNA**. Per comandi e isolamento dei test vedere [TESTING.md](../TESTING.md).
