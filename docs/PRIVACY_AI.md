# Privacy and AI — release preparation

## Implemented interface

All three widget versions show an AI introduction before the first conversation in a browser tab. The notice identifies Groq processing, possible AI errors and asks customers not to provide personal or health information. The black “Inizia la consulenza” button advances at the customer's pace. Its versioned `sessionStorage` preference is **not legal consent** and is not sent to the backend. Closing before advancing shows the notice again on reopening; changing `NOTICE_VERSION` also shows it again.

The header retains “Assistente AI” and a privacy button. The privacy screen describes actual message processing, same-tab browser history and server expiry after 24 hours of inactivity, renewed by completed messages. Cleanup is periodic; restart can end availability earlier. This is an operational explanation, **not a finalized GDPR notice**. Chat controls are hidden/inert while another screen is visible, with focus restoration and a reduced-motion alternative to the short fade. No notice countdown or model call is used.

The installed widget also sends a credential-free, no-referrer request to the Render `/health` endpoint after storefront page load, even if a visitor never opens the chat. A ten-minute timestamp in sessionStorage limits repeat requests in the same tab; in-memory throttling applies when storage is blocked. No conversation or product data is attached. Render still receives the connection and origin/IP metadata. Include this pre-connection in Etualy's privacy and provider review before public launch.

## Decisions required with Etualy before public launch

The optional five-star feedback prototype is disabled for the first public release through `FEEDBACK_PREVIEW_ENABLED = false` in all three widget versions. Its interface code remains available for an explicit company demonstration. Even when enabled, it only holds the chosen rating and a minimal product/variant summary in page memory; nothing is sent to the backend or saved for developer retrieval. Before enabling production collection, Etualy must approve the analytics purpose and notice, the lawful basis/consent handling, a retention period, access controls and durable storage. A random consultation ID linked to product choices is pseudonymous, not automatically anonymous. Render Free's local filesystem cannot reliably store feedback across restarts or deploys. Purchase attribution requires a separate Shopify integration and must never infer a sale merely from opening the cart.

**Groq configuration — 11 October 2026:** the project owner confirmed enabling **Global Zero Data Retention**. This records the owner's confirmation; the account dashboard was not independently inspected. Confirm that the deployed API key belongs to this organization when preparing release evidence. Browser/backend retention remains separate, and R06 is still open for the remaining work.

- Identify controller, roles of the developer and service providers, privacy contact and applicable legal basis. Do not assume that advancing past the notice is consent.
- Approve a complete notice covering purposes, categories of data, recipients, retention and rights. Provide its public URL and replace/extend the technical privacy screen with the approved material.
- Verify agreements with hosting and model providers, international transfers and safeguards. ZDR does not replace this work.
- Preserve release evidence of the owner-confirmed **Global ZDR** setting and its association with the deployed API key. Recheck this when switching organizations or credentials; do not equate ZDR with complete privacy compliance.
- Assess storage and retention separately for browser, SQLite sessions, replay receipts, hosting/provider logs and any backups. Expiry/reset delete application rows; they do not establish erasure of every physical copy, SQLite WAL or provider log.
- Review operational logging and deletion procedures, including error cases and access permissions. Avoid recording customer messages, credentials or prompt bodies without a justified need.
- Decide whether to use theme fonts or company-hosted fonts. The widget currently still loads Google Fonts; this has not been changed by the introductory-screen implementation.

## Scope and pending validation

This change implements the introduction and persistent access to technical privacy details. It does not change backend retention, provider settings, contracts, fonts or the existing reset API. R06 stays open until the remaining technical reviews and company decisions are completed. Browser regression fixtures advance past the introduction before ordinary chat checks; dedicated introduction/privacy checks still need authorization and execution.

Manually validate first entry, return navigation, keyboard/screen-reader reading, large text and mobile layout in the installed theme. Check the introductory preference across page navigation and after a notice version update, without interpreting it as proof of reading or consent.

References: [Groq data controls](https://console.groq.com/docs/your-data), [AI Act transparency](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50), [EDPB compliance guide](https://www.edpb.europa.eu/sme/be-compliant/be-compliant_en).
