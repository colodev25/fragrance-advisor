# Rete, tema e accessi: verifica di consegna

Procedura preparata il 15 ottobre 2026. Le impostazioni dell'account Render e la policy del tema Shopify vanno osservate nell'ambiente effettivo prima di dichiarare superato il collaudo. Usare soltanto dati fittizi; conservare le schermate nel dossier riservato, oscurando identificativi e segreti.

## 1. Origini browser

Nel Render Environment del servizio API verificare `ALLOWED_ORIGINS`. Per il negozio pubblico la proposta è `https://etualy.com,https://www.etualy.com`; aggiungere soltanto origini di anteprima realmente necessarie. Salvare l'impostazione e attendere il riavvio/deploy, perché l'applicazione la legge all'avvio. L'origine comprende schema, host e porta eventuale, senza percorso né slash finale.

Nel browser aprire la pagina del negozio e controllare in Network l'header `Origin` delle richieste `/chat` e `/reset`. Controllare il preflight `OPTIONS` e la risposta effettiva da entrambe le origini ammesse. Ripetere da un'origine di prova non ammessa: il browser deve bloccare la lettura della risposta. Verificare che `Retry-After` sia leggibile quando l'API restituisce un limite. Registrare origine, data, commit distribuito e risultato.

CORS governa l'accesso del browser alla risposta: richieste dirette all'API restano possibili. Non usarlo come autenticazione o come limite di capacità.

## 2. Proxy e identificazione del visitatore

L'applicazione usa `request.client.host` per i limiti per visitatore e ignora `X-Forwarded-For` letto direttamente. Uvicorn può normalizzare `request.client` tramite gli header inoltrati dai proxy considerati fidati. Render documenta `FORWARDED_ALLOW_IPS=*` come default Python: verificare il valore effettivo sul servizio, la topologia di ingresso e la normalizzazione degli header prima di cambiarlo. Non copiare indirizzi di proxy trovati in esempi o impostare una lista IP presunta.

In staging, far eseguire richieste con dati fittizi da due reti indipendenti e osservare i contatori/limiti senza registrare IP completi o testi. Provare anche un header `X-Forwarded-For` contraffatto inviato dal client: non deve consentire di scegliere arbitrariamente il bucket. Se la prova fallisce, documentare la causa e correggere la configurazione di Uvicorn o della rete prima del pubblico. Non creare un endpoint che esponga IP o header di tutti i visitatori.

`RATE_LIMIT_TRUST_PROXY_HEADERS` è deprecata e ignorata dal codice: non usarla. I limiti attuali sono locali al singolo processo; qualsiasi passaggio a più worker/istanze richiede una revisione separata.

## 3. Policy del tema Shopify

Sulla copia di anteprima del tema aprire la Console e Network, poi verificare se esiste una Content Security Policy tramite header o tag `meta`. Controllare che lo script e lo stile del widget siano eseguiti e che `connect-src` permetta `https://fragrance-advisor-api.onrender.com`; controllare anche immagini prodotto e chiamate Shopify della scheda/carrello. Annotare eventuali violazioni CSP esatte, senza esportare cookie o HAR grezzi.

Con il responsabile del tema, scegliere la modifica più ristretta compatibile con la policy effettiva. Se una policy blocca script o stili inline, valutare l'integrazione come asset del tema e gli eventuali nonce/hash previsti dall'ambiente; non aggiungere `unsafe-inline` globalmente per risolvere una singola violazione. Dopo la modifica ripetere consulenza, formati e carrello su desktop e mobile.

## 4. Proprietà e continuità degli accessi

Registrare nel dossier riservato l'owner aziendale e un sostituto per GitHub, Render, Groq e Shopify. Dare accessi individuali con i soli permessi necessari, MFA e recupero verificato. Per il tema usare l'invito collaboratore Shopify con permessi adeguati; non condividere la password del proprietario.

Per ogni segreto registrare solo nome, destinazione, owner e riferimento nel gestore password approvato. La rotazione della chiave Groq richiede: nuova chiave nell'organizzazione approvata, aggiornamento Render e GitHub Actions, prova chat e arricchimento con dati fittizi, revoca della precedente, verifica finale e registrazione della data. Riesaminare Global ZDR se cambia organizzazione o chiave. Provare che un referente aziendale possa revocare gli accessi dello sviluppatore senza interrompere la gestione del servizio.

## Esito

Compilare nel dossier privato le decisioni D11–D12 e le evidenze E10/E12. Il controllo T26 in `ACCEPTANCE.md` copre le prove di origini e header contraffatti. Conservare per ogni prova commit, configurazione oscurata, data, esito e responsabile. Un risultato locale non certifica la configurazione Render o il tema che verrà pubblicato.

Fonti: [Render, variabili predefinite](https://render.com/docs/environment-variables), [Shopify, pratiche di sicurezza](https://shopify.dev/docs/apps/build/security/following-security-best-practices).
