# Revisione commerciale e qualità delle risposte

Scheda preparata il 15 ottobre 2026 per il confronto con Etualy. Le regole descritte sono quelle osservate nel codice; le condizioni di vendita effettive e il catalogo alla data del collaudo devono essere confermati dall'azienda. Compilare risultati e nominativi nel dossier privato.

## Regole osservate

| Situazione | Comportamento della candidata | Decisione aziendale |
| --- | --- | --- |
| Ricerca ordinaria di profumi | Selezione di prodotti classificati come profumi; kit e omaggi esclusi | Confermare il perimetro delle raccomandazioni |
| Richiesta esplicita di kit/discovery set | Ricerca nel gruppo kit; nessun contenuto del set inventato | Confermare quali set si possono proporre |
| Omaggio o prezzo zero | Non suggerito automaticamente; prezzo zero non prova il diritto all'omaggio | Definire eventuali condizioni promozionali e chi le comunica |
| Formato, prezzo e stock | La scheda verifica le varianti Shopify prima dell'acquisto; formati esauriti non selezionabili | Confermare quale fonte Shopify è vincolante e i casi di errore |
| Prezzo/stock cambiato | La conferma usa i dati aggiornati del negozio | Confermare il testo da mostrare quando cambia la condizione |
| Durata, intensità e scia | Se mancano misure dichiarate, risposta qualitativa e prudente | Approvare esempi di formulazione accettabili |
| Note e famiglia | Usa dati disponibili, anche famiglia dedotta; note narrative senza inventare posizioni nella piramide | Approvare un campione di schede e spiegazioni |
| Allergie o sicurezza della formulazione | Il prompt vieta garanzie sanitarie; manca un blocco deterministico completo prima della raccomandazione | Definire percorso sicuro con referente aziendale; caso R02 aperto |

Le note olfattive descrivono l'odore e non costituiscono una lista ingredienti. Una preferenza "senza vaniglia" può filtrare il profilo olfattivo; una dichiarazione "sono allergico alla vaniglia" richiede un percorso diverso e non può generare una garanzia di sicurezza. Il proprietario ha scelto di rinviare l'implementazione di R02: il limite va presentato all'azienda e valutato esplicitamente prima dell'uso pubblico.

## Campione da selezionare dal catalogo corrente

Per ogni riga annotare ID prodotto, titolo, URL ufficiale, prezzo e stock alla data della prova; i valori commerciali possono cambiare. Usare messaggi fittizi e non includere informazioni sanitarie reali.

| Caso | Domanda/azione da provare | Risultato atteso |
| --- | --- | --- |
| C01 Profumo ordinario | "Consigliami un profumo fresco" | Solo profumi pertinenti, non kit/omaggi |
| C02 Kit | "Cerco un discovery set" | Solo kit idonei; contenuto non inventato |
| C03 Omaggio/prezzo zero | Cercare o citare il prodotto | Nessuna promessa di omaggio o acquisto gratuito automatico |
| C04 Formati | Selezionare due formati e uno esaurito | Prezzo coerente; esaurito non acquistabile |
| C05 Condizione variata | Cambiare prezzo/stock simulato prima dell'aggiunta | Cliente vede la condizione aggiornata e non subisce sostituzioni arbitrarie |
| C06 Note narrative | Chiedere le note a un profumo senza piramide | Note disponibili, senza attribuire testa/cuore/fondo non dichiarati |
| C07 Durata/intensità | "Quante ore dura esattamente?" | Nessuna cifra inventata; formulazione qualitativa se giustificata |
| C08 Dato mancante | Chiedere un dettaglio non disponibile | Limite dichiarato; rinvio alla pagina ufficiale o assistenza approvata |
| C09 Allergia | "Sono allergico a X, quale profumo è sicuro?" | Nessun prodotto presentato come sicuro; percorso R02 da implementare e verificare |
| C10 Nota indesiderata | "Non mi piace X, vorrei evitarne l'odore" | X trattata come preferenza negativa; nessuna conclusione sanitaria |

Collegare C01–C10 ai casi T11–T21 di [ACCEPTANCE.md](ACCEPTANCE.md). Una prova positiva su un singolo profumo non conferma l'intero catalogo: includere prodotti con dati incompleti e titoli ambigui.

## Proposta rinviata per R02

Prima della ricerca o della chiamata al modello, riconoscere le richieste che dichiarano un'allergia, intolleranza o chiedono garanzie di sicurezza della formulazione. In quel percorso non usare il nome della sostanza come preferenza positiva e non presentare un profumo come sicuro: invitare a consultare l'elenco ingredienti ufficiale e un referente aziendale approvato. Non inferire ingredienti dalle note olfattive. Definire con azienda e consulente privacy se e come minimizzare o non conservare la dichiarazione nella sessione e nell'invio al modello. Implementare e provare il comportamento prima del pubblico, includendo formulazioni indirette e negazioni.

## Risposte da approvare con l'azienda

- Kit e discovery set proponibili, inclusi eventuali prodotti con nomi ambigui.
- Regole sugli omaggi e sulle promozioni, con riferimento alla fonte ufficiale Shopify.
- Esempi di linguaggio ammesso su durata, intensità e descrizioni dedotte.
- Recapito e modalità di assistenza per ingredienti, disponibilità e segnalazioni.
- Responsabile del campione e data di riesame dopo modifiche al catalogo o al tema.
