# Widget UI/UX

The Etualy fragrance advisor is a self-contained chat widget, designed to bring guided fragrance discovery and product recommendations into the storefront.

## Discovery and conversation

- **Proactive entry point:** a floating launcher opens the advisor; a short invitation appears after a delay and can be dismissed.
- **Two ways to get started:** customers can follow the four-step guided consultation or begin with a free-form question about notes, fragrances or occasions.
- **Quick replies and progress:** contextual choice chips make guided answers easy to select, while a progress bar indicates the current step.
- **Choosing the right product:** ambiguous names show a short clarification with brand/full-title buttons instead of a guessed product card. The choice survives navigation in the same tab; the original budget and request resume after confirmation. Missing requested versions are explained, and spelling suggestions require confirmation. Existing quick replies support this flow on desktop and mobile.
- **Preferences that carry forward:** budget, recognized note exclusions and preferences remain active in subsequent searches. Both discovery modes prioritize confirmed matches; partial alternatives explain their differences. Unclear note constraints or conflicting budgets ask for clarification, with no misleading recommendation cards.
- **Chat continuity:** the session identifier, private credential and version, structured messages, product data, quick replies, guided step and unsent draft are saved in sessionStorage. Restoring recreates elements and actions across pages in the same browser tab. Expanded card panels are also retained; cart confirmations are not restored as current cart contents; closing the tab ends this local continuity.
- **Natural chat feedback:** message bubbles, smooth scrolling and an animated typing indicator keep the conversation readable. Longer waits show progressive status messages for requests that may be delayed by a backend cold start.

## Product exploration

- **Product cards:** recommendations can show the brand, fragrance name, family or type, price, story, olfactory notes and links to the product page and cart.
- **Expanded fragrance details:** guided and free-chat cards open a detail panel from the information button. It shows the story, available pyramid stages and profile; its height adapts to the message viewport, up to 420 px, with internal scrolling for longer content. Close actions remain outside that scrolling area.
- **Reading follows the selected card:** opening information scrolls only the conversation to the selected card, keeping its details above the input bar even when other recommendations follow. Each toggle cancels an earlier smooth scroll, and automatic browser scroll anchoring is disabled in the message area to avoid competing movements during consecutive openings. Reduced-motion preferences disable the smooth movement.
- **Additional olfactory notes:** notes whose position is unknown appear separately as “Altre note riportate”, or “Note riportate” when no pyramid is available, with “Posizione nella piramide non specificata”. Duplicates of positioned notes are removed; empty stages are omitted and missing notes receive a short message. Older saved cards retain their unclassified accord summary.
- **Clear fragrance profile:** concentration/type, recipient and season are separate items, for example “Eau de Parfum • Unisex • Primavera / Estate”. Source type strings are cleaned to avoid a repeated recipient, and season labels omit internal derivation annotations. Older saved and received profiles use the same display cleanup.
- **Keyboard navigation:** the detail button exposes its expanded state. The inactive side is excluded from interaction, and closing the panel returns focus to the information button. Both note sections and the expanded state survive page navigation.
- **Image loading and recovery:** product images load lazily with a shimmer placeholder and fade-in. Failed or unavailable images show a fragrance-themed fallback icon.
- **Verified cart:** on etualy.com, the same button checks the selected Shopify variant and adds one unit only after its current price and options have been presented. Success appears only after Shopify confirms the addition. “Vai al carrello” then opens the existing cart in a new tab, without adding again. Pending operations prevent duplicate clicks; unavailable variants and uncertain results receive clear messages. Outside the store, the button opens the product page without claiming an addition.

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

## Visual language

The interface uses a restrained black, white and warm-gold palette, with Cormorant Garamond for editorial fragrance titles and Plus Jakarta Sans for interface text. The floating launcher uses a charcoal gradient, white fragrance icon and soft white glow to harmonize with the storefront's WhatsApp button; hover and keyboard focus keep the same monochrome style. Compact product cards, accord chips and subtle motion keep attention on the recommendation and its olfactory profile.

### Purchase integration

Variant titles come from the selected available Shopify variant, not fragrance tags. New ingestion records expose `variant_id`, `variant_title` and `variant_options`; old catalogs remain usable through their cart permalink ID. Before adding, the widget refreshes the exact variant through Shopify product JSON. A changed price or option requires a second explicit confirmation. Missing variants never fall back to another format. Network timeouts after submission do not trigger automatic retries: the customer is invited to inspect the cart.

The integration uses locale-aware, same-origin Shopify Ajax endpoints on `etualy.com` or `www.etualy.com`. It needs no secret or additional paid service. After a confirmed addition, the widget dispatches the native `cart:build` event when Etualy's Impulse theme and drawer form are available. The theme rebuilds drawer items, totals, quantity controls and the header counter without opening the drawer. Other themes keep the ordinary cart-link flow and require their own integration. The widget stays open after addition; opening the cart is a separate customer action.

Integration references: [Shopify Cart API](https://shopify.dev/docs/api/ajax/reference/cart) and [Shopify Product API](https://shopify.dev/docs/api/ajax/reference/product).

The Impulse adapter was checked against Etualy's public theme JavaScript (schema Impulse 7.4.1) on 9 October 2026. It deliberately avoids `ajaxProduct:added`, which opens the drawer. Theme updates must retain the `cart:build` contract or adapt this hook; the widget does not replace theme markup or install extra drawer listeners.
