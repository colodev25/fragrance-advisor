# Widget UI/UX

The Etualy fragrance advisor is a self-contained chat widget, designed to bring guided fragrance discovery and product recommendations into the storefront.

## Discovery and conversation

- **Proactive entry point:** a floating launcher opens the advisor; a short invitation appears after a delay and can be dismissed.
- **Two ways to get started:** customers can follow the four-step guided consultation or begin with a free-form question about notes, fragrances or occasions.
- **Quick replies and progress:** contextual choice chips make guided answers easy to select, while a progress bar indicates the current step.
- **Chat continuity:** the session identifier, structured messages, product data, quick replies, guided step and last message are saved in sessionStorage. Restoring the conversation recreates its elements and actions while navigating between pages in the same browser tab. Restarting clears local state and asks the backend to reset the previous session. Expanded card panels and cart feedback are also retained.
- **Natural chat feedback:** message bubbles, smooth scrolling and an animated typing indicator keep the conversation readable. Longer waits show progressive status messages for requests that may be delayed by a backend cold start.

## Product exploration

- **Product cards:** recommendations can show the brand, fragrance name, family or type, price, story, olfactory notes and links to the product page and cart.
- **Expanded fragrance details:** cards that support it open a slide-over panel with the fragrance story, key accords and profile details.
- **Image loading and recovery:** product images load lazily with a shimmer placeholder and fade-in. Failed or unavailable images show a fragrance-themed fallback icon.
- **Cart feedback:** adding a product gives immediate visual confirmation, then opens the store cart link.

## Resilience and mobile interaction

- **One request at a time:** input, send and retry controls are disabled while waiting, preventing repeated taps from sending duplicate messages. Restart remains available.
- **Retry after an error:** “Riprova ora” resends the specific failed message with its original identifier. If its response was already saved, the backend returns it without another model call. Sending a new message retires previous retry buttons to preserve conversation order.
- **Recovery across pages:** navigating during a pending request preserves its identifier and offers a retry after restoration, without duplicating the customer message. Previous saved errors without request identifiers remain visible but cannot be retried through their old buttons.
- **Safe restart:** restart cancels the local wait, creates a new session and ignores late responses from the previous conversation. The remote reset is coordinated with processing already underway; a model call that has started can still finish.
- **Responsive layout:** the desktop widget opens as a floating panel; on small screens it becomes a full-screen view with safe-area spacing.
- **Mobile keyboard and touch handling:** focusing the input brings it into view; interacting with or scrolling the conversation dismisses the keyboard. Opening the mobile widget locks background-page scrolling.
- **Reduced-motion support:** system preferences for reduced motion are respected by limiting transitions, animations and smooth scrolling.

## Content safety

- **Text and cards:** customer messages, model responses and product fields are inserted through DOM text and attribute properties. Received content cannot supply HTML elements or event handlers. The supported response formatting remains paragraphs, line breaks, bold text and links.
- **Links and images:** only absolute HTTP(S) URLs without credentials, whitespace, control characters or unsafe delimiters are accepted. Invalid links become plain text, invalid product links become inactive, and invalid images use the placeholder.
- **Stored conversation:** `etualy_chat_state_v1` contains versioned JSON tied to the current session. Restored fields are normalized and rendered through the same safe path; saved HTML is never reinserted. Invalid states are cleared. On the first load after upgrading, the previous HTML-based history is discarded and a new local session starts; this is not a deletion of every backend session.
- **Shopify integration:** `snippets/etualy-advisor.liquid` contains the same safe renderer as the standalone page. Updating `index.html` alone does not update a snippet already installed in a Shopify theme; publish the revised snippet there as well.

## Visual language

The interface uses a restrained black, white and warm-gold palette, with Cormorant Garamond for editorial fragrance titles and Plus Jakarta Sans for interface text. The floating launcher uses a charcoal gradient, white fragrance icon and soft white glow to harmonize with the storefront's WhatsApp button; hover and keyboard focus keep the same monochrome style. Compact product cards, accord chips and subtle motion keep attention on the recommendation and its olfactory profile.
