# Widget UI/UX

The Etualy fragrance advisor is a self-contained chat widget, designed to bring guided fragrance discovery and product recommendations into the storefront.

## Discovery and conversation

- **Resilient local state:** widget-owned storage operations fall back to page memory if the browser blocks storage or an attempted write fails. A single inline note warns that navigation may lose continuity; the conversation remains usable in the current page. Other storefront storage is not cleared.
- **Draft protection:** messages exceeding 2,000 characters remain editable, with a counter near the limit and an explanatory warning. Draft writes are delayed by 300 ms during typing and flushed on important actions, page hiding and navigation when the browser permits those events. Long pasted text is not silently truncated.
- **Bounded history:** local records and rendered messages are limited to 100, with a separate 1 MiB serialized-state budget. Older entries are removed first, preserving the latest exchange and focused or pending purchase actions. A quota error triggers one smaller-history retry before memory fallback. These interface limits do not change backend conversation memory.

- **AI introduction:** the first opening in a browser tab displays a centered notice below the header, with Groq processing, AI limitations and a reminder to avoid personal/health information. “Inizia la consulenza” opens the chat with a short fade; no countdown, automatic advance or consent checkbox. The versioned notice preference survives navigation in the same tab and DevTools reinsertion. Updating its version presents it again. “Assistente AI” remains visible in the header.
- **Privacy access:** introductory and header buttons open an internally scrollable information screen about message processing, browser history and server inactivity expiry. Returning preserves the conversation and restores focus; chat controls are hidden and inert while these screens are open. These technical explanations do not replace the company-approved privacy notice required before public launch.

- **Proactive entry point:** a floating launcher opens the advisor; a short invitation appears after a delay and can be dismissed.
- **Two ways to get started:** customers can follow the four-step guided consultation or begin with a free-form question about notes, fragrances or occasions.
- **Quick replies and progress:** contextual choice chips make guided answers easy to select, while a progress bar indicates the current step.
- **Choosing the right product:** ambiguous names show a short clarification with brand/full-title buttons instead of a guessed product card. The choice survives navigation in the same tab; the original budget and request resume after confirmation. Missing requested versions are explained, and spelling suggestions require confirmation. Existing quick replies support this flow on desktop and mobile.
- **Preferences that carry forward:** budget, recognized note exclusions and preferences remain active in subsequent searches. Both discovery modes prioritize confirmed matches; partial alternatives explain their differences. Unclear note constraints or conflicting budgets ask for clarification, with no misleading recommendation cards.
- **Chat continuity:** the session identifier, private credential and version, structured messages, product data, quick replies, guided step and unsent draft are saved in sessionStorage. Restoring recreates elements and actions across pages in the same browser tab. Expanded card panels are also retained; cart confirmations are not restored as current cart contents; closing the tab ends this local continuity.
- **Natural chat feedback:** message bubbles, smooth scrolling and an animated typing indicator keep the conversation readable. Longer waits show progressive status messages for requests that may be delayed by a backend cold start.
- **Early backend wake-up:** after the storefront page finishes loading, the widget asynchronously requests the lightweight Render `/health` endpoint. The request is limited to once every ten minutes per browser tab when sessionStorage is available (per page when it is blocked) and is repeated when opening the widget after a longer stay. It neither blocks storefront rendering nor calls Groq. This can overlap a Free-tier cold start with product browsing, but does not guarantee an immediate reply if the shopper starts chatting at once. The DevTools preview begins only when its script is pasted; the installed Shopify snippet begins on normal page load.

## Feedback preview

After a recommendation, the first click on the widget's close button opens an optional five-star screen styled like the AI introduction. Customers can skip it, close immediately with the button or Escape, and will not be asked again in the same consultation. After Shopify confirms a cart addition, clicking **Vai al carrello** opens the cart immediately in a new tab and leaves the optional feedback screen in the original tab. Uncertain or failed additions do not trigger it. Stars fill on desktop hover and on touch/click selection; keyboard access and reduced-motion settings remain supported.

This is an interface preview: the selected rating, recommended product IDs and confirmed added variant IDs exist only in page memory. No feedback request, server log or persistent record is created. The screen tells customers that their rating is not saved. Before production collection, agree on consent, notice, retention and durable restricted storage with Etualy; see [privacy preparation](PRIVACY_AI.md).

## Product exploration

- **Product cards:** recommendations can show the brand, fragrance name, family or type, price, story, olfactory notes and links to the product page and cart.
- **Expanded fragrance details:** guided and free-chat cards open a detail panel from the information button. It shows the story, available pyramid stages and profile; its height adapts to the message viewport, up to 420 px, with internal scrolling for longer content. Close actions remain outside that scrolling area.
- **Reading follows the selected card:** opening information scrolls only the conversation to the selected card, keeping its details above the input bar even when other recommendations follow. Each toggle cancels an earlier smooth scroll, and automatic browser scroll anchoring is disabled in the message area to avoid competing movements during consecutive openings. Reduced-motion preferences disable the smooth movement.
- **Restored detail sizing:** the same sizing rule runs when a detail panel opens, the widget becomes visible after the AI notice, or the conversation viewport changes. Restored open cards adapt to the available height; resize observation accounts for orientation and keyboard changes. A visible card being read stays aligned inside the conversation.
- **Additional olfactory notes:** notes whose position is unknown appear separately as “Altre note riportate”, or “Note riportate” when no pyramid is available, with “Posizione nella piramide non specificata”. Duplicates of positioned notes are removed; empty stages are omitted and missing notes receive a short message. Older saved cards retain their unclassified accord summary.
- **Clear fragrance profile:** concentration/type, recipient and season are separate items, for example “Eau de Parfum • Unisex • Primavera / Estate”. Source type strings are cleaned to avoid a repeated recipient, and season labels omit internal derivation annotations. Older saved and received profiles use the same display cleanup.
- **Keyboard navigation:** the detail button exposes its expanded state. The inactive side is excluded from interaction, and closing the panel returns focus to the information button. Both note sections and the expanded state survive page navigation.
- **Image loading and recovery:** product images load lazily with a shimmer placeholder and fade-in. Failed or unavailable images show a fragrance-themed fallback icon.
- **Verified cart:** on etualy.com, the same button checks the selected Shopify variant and adds one unit only after its current price and options have been presented. Success appears only after Shopify confirms the addition. “Vai al carrello” then opens the existing cart in a new tab, without adding again. Pending operations prevent duplicate clicks; unavailable variants and uncertain results receive clear messages. Outside the store, the button opens the product page without claiming an addition.
- **Stable card while adding:** an empty cart-status area takes no space during “Aggiunta…”. Explanations for errors or required customer choices still appear below the button when present.

## Resilience and mobile interaction

- **One request at a time:** input, send and retry controls are disabled while waiting, preventing repeated taps from sending duplicate messages. Restart remains available.
- **Retry after an error:** “Riprova ora” resends the specific failed message with its original identifier. If its response was already saved, the backend returns it without another model call. Sending a new message retires previous retry buttons to preserve conversation order.
- **Bounded waits:** after 60 seconds without a complete response, the widget stops the local wait and offers recovery of the same message. Late replies cannot overwrite a later request.
- **Respectful retries:** a server cooldown appears as a countdown on “Riprova”. Sending and retrying are temporarily disabled; the deadline survives page changes and local restart.
- **Recovery across pages:** navigating during a pending request preserves its identifier and offers a retry after restoration, without duplicating the customer message. Previous saved errors without request identifiers remain visible but cannot be retried through their old buttons.
- **Safe restart:** restart cancels the local wait, creates a new session and ignores late responses from the previous conversation. The remote reset is coordinated with processing already underway; a model call that has started can still finish.
- **Session recovery:** a session expires after 24 hours without a new completed message. If it has expired, disappeared from the server or advanced in another tab, the widget explains the restart, creates a fresh local session and keeps the message ready in the input. It never resends automatically or resets another tab's server state. Version checks travel with normal chat requests; page navigation adds no API call.
- **Responsive layout:** the desktop widget opens as a floating panel; on small screens it becomes a full-screen view with safe-area spacing.
- **Mobile keyboard and touch handling:** focusing the input brings it into view; interacting with or scrolling the conversation dismisses the keyboard. Opening the mobile widget locks background-page scrolling.
- **Reduced-motion support:** system preferences for reduced motion are respected by limiting transitions, animations and smooth scrolling.

## Content safety

- **Text and cards:** customer messages, model responses and product fields are inserted through DOM text and attribute properties. Received content cannot supply HTML elements or event handlers. The supported response formatting remains paragraphs, line breaks, bold text and links.
- **Links and images:** only absolute HTTP(S) URLs without credentials, whitespace, control characters or unsafe delimiters are accepted. Invalid links become plain text, invalid product links become inactive, and invalid images use the placeholder.
- **Stored conversation:** `etualy_chat_state_v1` now contains version-3 JSON tied to the private session credential, token, revision and deadline. Restored fields use the same safe renderer; saved HTML is never reinserted and invalid states are cleared. Previous version-1 and version-2 histories are retired once with an update notice, preserving a pending message or draft. Backend sessions are not globally deleted by this migration.
- **Shopify integration:** `snippets/etualy-advisor.liquid` contains the same safe renderer as the standalone page. Updating `index.html` alone does not update a snippet already installed in a Shopify theme; publish the revised snippet there as well.

New structured note sections require responses from the deployed backend that contain `olfactory_pyramid` and `unpositioned_notes`. The DevTools preview calls that remote API. Older saved cards keep their accord summary; after deploying both parts, begin a fresh conversation to obtain the new card data.

## Reliable descriptions and links

The advisor may use the available olfactory family whether explicit or inferred; no derivation label is added to customer cards. Without documented performance data, duration, intensity and trail may be discussed qualitatively as cautious impressions consistent with the available profile, without invented hours or guaranteed results. Olfactory notes do not certify ingredients or allergen absence.

Model-generated Markdown links appear as non-clickable text. Product/purchase actions accept only HTTPS URLs on `etualy.com` and `www.etualy.com`; product images also allow `cdn.shopify.com`. Exact host matching rejects lookalike domains, credentials and custom ports. These rules apply to restored cards too. The current catalog uses Etualy links and Shopify CDN images; a future hosting change requires updating the explicit allowlist in all widget variants. The fixed Groq documentation link in the privacy screen remains available.

## Visual language

The interface uses the storefront's black, white and neutral-gray palette, with Cormorant Garamond for fragrance titles and Plus Jakarta Sans for interface text. Former gold accents are now black or neutral gray; muted text uses a darker gray for legibility. The floating launcher retains its charcoal gradient, white fragrance icon and soft white glow. Compact product cards, accord chips and subtle motion keep attention on the recommendation and its olfactory profile.

## Accessibility

- Closed chat and invitation controls are inert and hidden from assistive technology. The invitation is a native button when shown.
- Opening focuses the chat title without automatically opening the mobile keyboard. Escape minimizes the chat and returns focus to the launcher; keyboard focus has a visible outline.
- Desktop remains non-modal. At widths up to 600 px the full-screen chat is modal: focus stays inside, background elements become inert, and scrolling is locked. Closing or switching to desktop restores the previous background inert and scroll-lock states. Newly inserted background elements are covered while the chat is open.
- The dialog, message input and conversation history have explicit names. A dedicated polite status region announces new responses, recommended product names and errors without rereading restored history. Existing purchase status announcements remain separate.
- Small mobile header/invitation controls have a minimum 44 px touch area. The standalone page permits zoom; input scrolling respects reduced-motion preferences.

Browser regression checks cover keyboard behavior, mobile isolation, state restoration, announcements and enlarged text at a 320 px viewport. Actual screen-reader behavior, browser zoom and interaction with the installed Shopify theme require manual validation before release; these checks are not a conformance certification.

### Purchase integration

Variant titles come from the selected available Shopify variant, not fragrance tags. New ingestion records expose `variant_id`, `variant_title` and `variant_options`; old catalogs remain usable through their cart permalink ID. Before adding, the widget refreshes the exact variant through Shopify product JSON. A changed price or option requires a second explicit confirmation. Missing variants never fall back to another format. Network timeouts after submission do not trigger automatic retries: the customer is invited to inspect the cart.

The integration uses locale-aware, same-origin Shopify Ajax endpoints on `etualy.com` or `www.etualy.com`. It needs no secret or additional paid service. After a confirmed addition, the widget dispatches the native `cart:build` event when Etualy's Impulse theme and drawer form are available. The theme rebuilds drawer items, totals, quantity controls and the header counter without opening the drawer. Other themes keep the ordinary cart-link flow and require their own integration. The widget stays open after addition; opening the cart is a separate customer action.

Integration references: [Shopify Cart API](https://shopify.dev/docs/api/ajax/reference/cart) and [Shopify Product API](https://shopify.dev/docs/api/ajax/reference/product).

The Impulse adapter was checked against Etualy's public theme JavaScript (schema Impulse 7.4.1) on 9 October 2026. It deliberately avoids `ajaxProduct:added`, which opens the drawer. Theme updates must retain the `cart:build` contract or adapt this hook; the widget does not replace theme markup or install extra drawer listeners.

### Format buttons and purchases from chat

Routine format changes and confirmed additions use the card's live price, selected option and cart button instead of messages below the action. A commercial change detected before submission requires a second click on “Conferma aggiunta”. Failures show a red border/text, error icon and brief shake; reduced-motion preferences disable the shake. Confirmed failures offer “Aggiunta fallita · Riprova”, while a lost or unconfirmed response offers “Esito incerto · Verifica carrello” without resubmitting. Exceptional explanatory messages remain visible when necessary to resolve stock, missing selections or uncertain outcomes.

On the Shopify storefront, cards load the product's current variants and show explicit format buttons under a “Formato” label. One price appears below the product header and updates immediately with the selected option. Multiple formats use the buttons as the selected-format indicator; a single format appears beside the price without a redundant selector. Selected options are highlighted; unavailable options are gray, disabled and marked “Esaurito”. The cart action occupies a dedicated full-width row. Only the selected ID is preserved across navigation; availability is reloaded, not trusted from history. Loading failures can be retried by the cart action. The widget stays scrolled to the latest content when appropriate, and manual selection keeps the purchase action visible.

Free-chat requests such as “aggiungi al carrello Iris 100 ml” prepare a card with that exact format and **Conferma aggiunta**. The same applies to “questo profumo” when the conversation identifies a single product. Ambiguous product references require clarification; ambiguous or unavailable formats require manual selection. No chat message, model output, restored card or retry automatically writes to the cart. One explicit confirmation adds one unit after a fresh Shopify check. Requests for available formats or the price of a specified size also show live cards rather than model-generated size lists.

Variant buttons display Shopify option titles, including other options when applicable; they do not infer bottle sizes from tags. The default catalog price remains the recommendation snapshot. Variant selection can change the purchase price; the customer sees the current price before confirming. Selecting variants runs in the storefront browser and does not create additional Groq calls. After an uncertain submitted addition, the card disables variant switching and offers a link to inspect the cart; after a confirmed addition, a different format can be chosen explicitly.
