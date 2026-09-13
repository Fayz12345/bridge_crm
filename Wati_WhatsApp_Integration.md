# WhatsApp in Bridge CRM

How WhatsApp works in the CRM today, how multiple business numbers are used, and whether we could talk to WhatsApp directly instead of through Wati.

Production uses **Wati** (`WHATSAPP_PROVIDER=wati`). A Meta Cloud API client also exists in the codebase but is a single-number stub: it cannot run broadcasts, contact sync, or per-rep numbers yet.

---

## What works today (Wati)

One Wati Business tenant can hold several WhatsApp numbers (paid add-ons, typically up to 25 including the default). The CRM picks which number to send from.

### Setup (admin)

1. Confirm extra numbers are connected in **the same** Wati Business account (one API token).
2. In the CRM, open **Users** and click **Sync Wati numbers**.
3. Edit each sales user and assign their WhatsApp number.
4. Leave a user on **Company default** to send from `WATI_CHANNEL_NUMBER`.

Contacts stay in **one shared Wati address book**. CRM → Wati contact sync does not need to be redone per number. Templates are also shared: submit once, Wati pushes to all numbers.

### 1:1 chat (lead or account)

- Session reply (free text) and first-contact template send from the **logged-in user’s** assigned number.
- The thread header shows which number you are sending from.
- Each bubble stores the business number that sent or received the message.

Free-text replies only work inside the **24-hour window for that number**. First outreach, or a reply after the window, still needs an approved template. That is a Meta rule, not a Wati or CRM choice.

### Broadcasts

On bulk WhatsApp / campaign send, use **Send from** to choose the business number for the campaign. If you do not change it, the CRM uses your assigned number, then the company default.

### Incoming messages

Wati webhooks include which business number received the chat. The CRM stores that number and notifies:

- the lead/account **owner**, and
- any CRM user **assigned to that number**.

The inbox is still **one thread per lead or account**. If the same customer messages two reps on two numbers, those chats currently **merge** in the CRM.

### What we are not doing yet

- Separate CRM threads per business number
- Blocking a user from broadcasting on someone else’s number (admins assign numbers; broadcasts have a picker)
- Creating Wati operators 1:1 with CRM users (Wati login and CRM login stay separate)

---

## Environment

Minimum for Wati:

| Variable | Purpose |
|---|---|
| `WHATSAPP_PROVIDER=wati` | Use Wati instead of Meta Cloud API |
| `WATI_API_ENDPOINT` | Tenant API URL (no `/api/v1` suffix) |
| `WATI_ACCESS_TOKEN` | Bearer token |
| `WATI_CHANNEL_NUMBER` | Default / company number (digits) |
| `WHATSAPP_DEFAULT_TEMPLATE` | Approved template for first contact / broadcast fallback |
| `WATI_WEBHOOK_SECRET` | Optional webhook auth |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | Needed to cancel templates in Wati |

Webhook URL (configure in Wati):

`https://<crm-host>/api/wati/webhook`

---

## Could we run WhatsApp from the CRM without Wati?

**Yes, technically.** WhatsApp Business is Meta’s product. Wati is a paid layer on top of the **WhatsApp Cloud API**. The CRM already has a Meta client (`integrations/meta_whatsapp.py`) behind `WHATSAPP_PROVIDER=meta`.

**It would not make the requirements easier.** Per-rep numbers, 24-hour session windows, approved templates, quality scores, and messaging tiers all come from **Meta**, not Wati. Dropping Wati does not remove those rules.

### What native Meta would still require

- A WhatsApp Business Account (WABA) and a Meta app
- Each number registered on that WABA (a number cannot sit on two WABAs)
- Graph API token, `phone_number_id` per line, and webhooks to the CRM
- Template submission and approval in Meta Business Manager (or our own UI on Graph)
- Our own broadcast fan-out (Meta has no Wati-style `sendTemplateMessages` campaign object)
- Our own contact directory (Meta has no Wati address book)
- Media download/storage if we want images in the CRM thread

### What the CRM can do on Meta today

| Capability | Wati (current) | Native Meta in this CRM |
|---|---|---|
| 1:1 session text | Yes, with channel | Yes, **one** `WHATSAPP_PHONE_NUMBER_ID` |
| Template send | Yes, with channel | Yes, one number |
| Broadcast / campaign | Yes | Not implemented |
| List / assign numbers | Yes | Not implemented |
| Contact sync | Yes | Not implemented |
| Template create / sync UI | Yes | Not implemented |
| Inbound webhooks | Yes (`/api/wati/webhook`) | Partial (`/api/whatsapp/webhook`) |

Building “native” multi-number to match today’s Wati behaviour is **more** CRM work, not less: we would re-implement broadcasts, number catalog, contact sync, and template admin on Graph, and we would lose Wati Team Inbox unless everyone replies only in the CRM.

### Recommendation

Stay on **Wati** for this phase. The tedious part of “each rep has a number” was CRM mapping (assign number → pass `channel_number` on send → store it on inbound). That is in place. Moving off Wati is a product change (own the inbox and Meta ops), not a shortcut around WhatsApp limits.

Revisit native Meta if you want to stop paying Wati, stop using Wati’s inbox, and are ready to treat the CRM as the only place reps reply.

---

## Limits that do not go away (Wati or native)

- Extra numbers are paid (Wati add-on and/or Meta).
- Credits / rate limits: Wati shares plan credits across numbers; Meta gives each number its **own** quality score and messaging tier (new numbers start low).
- 24-hour customer-care window is per number.
- Contacts and templates are shared on one Wati tenant (and on one WABA).
- Wati operators and CRM users are different identities unless we sync them on purpose.
