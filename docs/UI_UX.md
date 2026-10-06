# Widget UI/UX

The Etualy fragrance advisor is a self-contained chat widget, designed to bring guided fragrance discovery and product recommendations into the storefront.

## Discovery and conversation

- **Proactive entry point:** a floating launcher opens the advisor; a short invitation appears after a delay and can be dismissed.
- **Two ways to get started:** customers can follow the four-step guided consultation or begin with a free-form question about notes, fragrances or occasions.
- **Quick replies and progress:** contextual choice chips make guided answers easy to select, while a progress bar indicates the current step.
- **Chat continuity:** the session identifier, conversation markup, quick replies, guided step and last message are saved in sessionStorage. This restores the conversation while navigating between pages in the same browser tab. Restarting the consultation clears the local chat state and asks the backend to reset the previous session.
- **Natural chat feedback:** message bubbles, smooth scrolling and an animated typing indicator keep the conversation readable. Longer waits show progressive status messages for requests that may be delayed by a backend cold start.

## Product exploration

- **Product cards:** recommendations can show the brand, fragrance name, family or type, price, story, olfactory notes and links to the product page and cart.
- **Expanded fragrance details:** cards that support it open a slide-over panel with the fragrance story, key accords and profile details.
- **Image loading and recovery:** product images load lazily with a shimmer placeholder and fade-in. Failed or unavailable images show a fragrance-themed fallback icon.
- **Cart feedback:** adding a product gives immediate visual confirmation, then opens the store cart link.

## Resilience and mobile interaction

- **Retry after an error:** a clear recovery message and “Riprova ora” button let customers resubmit their last message after a failed request.
- **Responsive layout:** the desktop widget opens as a floating panel; on small screens it becomes a full-screen view with safe-area spacing.
- **Mobile keyboard and touch handling:** focusing the input brings it into view; interacting with or scrolling the conversation dismisses the keyboard. Opening the mobile widget locks background-page scrolling.
- **Reduced-motion support:** system preferences for reduced motion are respected by limiting transitions, animations and smooth scrolling.

## Visual language

The interface uses a restrained black, white and warm-gold palette, with Cormorant Garamond for editorial fragrance titles and Plus Jakarta Sans for interface text. Compact product cards, accord chips and subtle motion keep attention on the recommendation and its olfactory profile.
