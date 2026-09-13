#  WhatsApp multi-number (Wati)
---

## Reply you can send

We can support **one Wati Business account with several WhatsApp numbers**, and have the CRM send from each sales person’s number.

**What is in the CRM now**

1. **Assign a WhatsApp number to each CRM user** (Users page → Sync Wati numbers → pick a number per rep). Unassigned users still send from the company default number.
2. **1:1 chat** on a lead or account goes out from the **logged-in user’s** number. The thread shows which number you are sending from.
3. **Broadcasts** have a **Send from** picker so a campaign can go out from a chosen business number.
4. **Incoming replies** record which Bridge number received the message. We notify the record owner **and** the user assigned to that number.

**Contacts**

In the **CRM**, each salesperson already has their own book of business (lead/account owner). That is the system of record.

In **Wati**, contacts stay in **one shared address book** for the whole tenant. Extra WhatsApp numbers do not give each rep a private Wati contact list. That is a Wati/Meta limit, not something we can split inside one Wati account.

If “my contact must always send from my number,” we can next change 1:1 send to use the **record owner’s** number instead of whoever is logged in. If the need is “Sara must not see Ahmed’s contacts in Wati,” that would require **separate Wati accounts** (or using the CRM as the only inbox and not relying on Wati Team Inbox).

**Could we drop Wati and talk to WhatsApp natively?**

Yes, technically. WhatsApp is Meta’s Cloud API; Wati is a layer on top. The CRM already has a Meta stub, but it is **one number only** today (no broadcasts, no contact sync, no per-rep numbers).

Going native would **not** remove Meta’s rules: 24-hour session window, approved templates, quality scores, messaging tiers, and “a number can only sit on one WhatsApp Business Account.” Matching what we have with Wati would be **more** CRM work (rebuild broadcasts, number catalog, contacts, template admin) and we would lose Wati’s inbox unless everyone replies only in the CRM.

**Recommendation:** stay on Wati for this phase. The mapping (user → number → send/inbound) is in place. Revisit native Meta only if you want to stop using Wati’s product and own Meta operations in the CRM.

**What we still need from you**

- Confirm all extra numbers are on **one** Wati Business account (one API token).
- Who owns which number (and whether there is also a company/marketing number).
- Confirm you are okay with a **shared** Wati contact book, with ownership kept in the CRM.
- Whether 1:1 send should be **logged-in user** (current) or **record owner**.

---

## What we changed in the CRM

Branch: `sandbox` (uncommitted work on top of the merged CSV import and Wati contact-sync PRs).

### Behaviour

- New catalog of Wati business numbers (`crm_whatsapp_channels`), with each CRM user optionally linked to one number.
- Admin **Users** list/form: WhatsApp number column, assign number, **Sync Wati numbers**.
- Company default number is seeded from `WATI_CHANNEL_NUMBER` so the picker is not empty.
- 1:1 session and template send pass that user’s `channel_number` into Wati (session, template, history sync).
- Broadcasts pass the chosen **Send from** number into Wati’s bulk template API.
- Outbound messages store `from_number`; inbound webhooks store `channelPhoneNumber` as `to_number`.
- Chat bubbles and the composer show which business number was used.
- Inbound notifications go to the lead/account owner **and** users assigned to the number that received the chat.

### Main files

- `crm/whatsapp/channels.py` — catalog, user mapping, sync from Wati, send-from resolution
- `integrations/wati.py` / `integrations/whatsapp.py` — `channel_number` / `channelPhoneNumber` on send, list numbers, history
- `db/schema.py` / `db/bootstrap.py` — channels table + `crm_users.whatsapp_channel_id`
- Users, thread, bulk WhatsApp templates and routes
- `crm/whatsapp/inbound.py` — inbound channel + notify assignees
- `tests/test_whatsapp_channels.py`
- `Wati_WhatsApp_Integration.md` — longer product/tech notes (native vs Wati, env vars, limits)

### Not in this slice

- Separate CRM threads if the same customer texts two reps
- Private Wati contact lists per salesperson
- Native Meta multi-number (still a single-number stub)
