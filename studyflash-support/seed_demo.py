"""
seed_demo.py
============
Seeds the studyflash_support database with:
  - 5 real support tickets from uploaded files (DE, NL, NL, DE, IT)
  - 1 English translation of ticket_3917 (so we have EN + DE versions)
  - A mock SF database (studyflash_mock) with user records for each sender
  - Full enrichment data (sf_user_data, sentry_events, posthog_recordings, similar_tickets)
    inserted directly — no need for live Sentry/PostHog APIs

Run from inside the studyflash-support/ folder:
  python seed_demo.py

Requirements: psycopg (pip install psycopg)
"""

import psycopg
import uuid
import json
from datetime import datetime, timezone, timedelta
import random

# ── Connection ──────────────────────────────────────────────────────────────────
SUPPORT_DB = dict(host="127.0.0.1", port=5433, dbname="studyflash_support",
                  user="postgres", password="password")
MOCK_SF_DB = dict(host="127.0.0.1", port=5433, dbname="studyflash_mock",
                  user="postgres", password="password")

def now(offset_hours=0):
    return datetime.now(timezone.utc) + timedelta(hours=offset_hours)

def iso(dt):
    return dt.isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Create and populate the mock Studyflash database
# ═══════════════════════════════════════════════════════════════════════════════

print("\n── STEP 1: Creating mock SF database ──────────────────────────────")

# Create the database if it doesn't exist (connect to default postgres db first)
with psycopg.connect(host="127.0.0.1", port=5433, dbname="postgres",
                     user="postgres", password="password",
                     autocommit=True) as conn:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'studyflash_mock'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE studyflash_mock")
        print("  Created database: studyflash_mock")
    else:
        print("  Database studyflash_mock already exists")

with psycopg.connect(**MOCK_SF_DB) as conn:
    cur = conn.cursor()

    # Create tables that match what _fetch_sf_user_data queries
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            plan TEXT NOT NULL,
            stripe_customer_id TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS refunds (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            amount_eur NUMERIC(8,2),
            reason TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            last_active_at TIMESTAMPTZ
        )
    """)

    conn.commit()
    print("  Tables created (users, refunds, sessions)")

    # ── User records — one per ticket sender ──────────────────────────────────
    # Format: (email, plan, joined_days_ago, last_active_days_ago, prev_refunds, stripe_id)
    USERS = [
        # ticket_3917 (EN translated) — Angelina Arendt
        ("angelina.arendt@gmail.com", "Pro Annual",
         420, 62, 0, "cus_ArenDT9182jX"),

        # ticket_3923 — Dutch mobile user (no name given)
        ("klarna_user_3923@gmail.com", "Pro Monthly",
         180, 14, 1, "cus_KLarn3923mx"),

        # ticket_4072 — Dutch referral question
        ("referral_user_4072@gmail.com", "Free",
         45, 3, 0, None),

        # ticket_4338 — German podcast question
        ("podcast_user_4338@gmail.com", "Pro Annual",
         90, 1, 0, "cus_Pod4338deXQ"),

        # ticket_4348 — Gaia Pistone (Italian formal dispute)
        ("gaia.pistone@gmail.com", "Pro Annual",
         730, 44, 0, "cus_GaiPis7301it"),
    ]

    user_ids = {}
    for email, plan, joined_days_ago, last_active_days_ago, prev_refunds, stripe_id in USERS:
        uid = str(uuid.uuid4())
        joined = now(-24 * joined_days_ago)
        last_active = now(-24 * last_active_days_ago)

        cur.execute("""
            INSERT INTO users (id, email, created_at, plan, stripe_customer_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET plan=EXCLUDED.plan
            RETURNING id
        """, (uid, email, joined, plan, stripe_id))
        actual_uid = cur.fetchone()[0]
        user_ids[email] = actual_uid

        # Insert sessions
        cur.execute("""
            INSERT INTO sessions (user_id, last_active_at)
            VALUES (%s, %s)
        """, (actual_uid, last_active))

        # Insert previous refunds
        for _ in range(prev_refunds):
            cur.execute("""
                INSERT INTO refunds (user_id, amount_eur, reason, created_at)
                VALUES (%s, %s, %s, %s)
            """, (actual_uid, 9.99, "subscription_cancellation",
                  now(-24 * (joined_days_ago - 30))))

        print(f"  User: {email} | {plan} | joined {joined_days_ago}d ago | "
              f"last active {last_active_days_ago}d ago | {prev_refunds} prev refunds")

    conn.commit()
    print("  ✓ Mock SF database populated")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Insert tickets into studyflash_support
# ═══════════════════════════════════════════════════════════════════════════════

print("\n── STEP 2: Inserting tickets ───────────────────────────────────────")

with psycopg.connect(**SUPPORT_DB) as conn:
    cur = conn.cursor()

    # Get current max ticket number
    cur.execute("SELECT COALESCE(MAX(ticket_number), 1000) FROM tickets")
    max_num = cur.fetchone()[0]

    # ── Ticket definitions ─────────────────────────────────────────────────────
    # Each entry: (ref_key, ticket_number, subject, sender_email, sender_name,
    #              category, language, priority, tags, body_text)
    TICKETS = [

        # ── ticket_3917 ENGLISH (translated from German original) ────────────
        {
            "key": "3917_en",
            "number": max_num + 1,
            "subject": "Cancellation under the Fair Consumer Contracts Act",
            "email": "angelina.arendt@gmail.com",
            "name": "Angelina Arendt",
            "category": "refund_request",
            "language": "en",
            "priority": "high",
            "tags": ["subscription-cancellation", "legal-reference", "ai-draft", "bgb-309"],
            "body": (
                "Hello,\n\n"
                "Under the Fair Consumer Contracts Act (Gesetz für fairere Verbraucherverträge), "
                "a tacit contract renewal is still valid provided that consumers are given a "
                "cancellation notice period of at most one month. My contract was concluded after "
                "01.03.2022, so this law applies to it.\n\n"
                "I hereby cancel my contract with StudyFlash (account: angelina.arendt@gmail.com) "
                "with effect from the earliest possible date. Since my contract was automatically "
                "renewed after the expiry of the minimum term, I am exercising my statutory right "
                "of cancellation with one month's notice pursuant to § 309 No. 9 BGB.\n\n"
                "Please confirm receipt of this cancellation notice and the exact contract end "
                "date by email as soon as possible.\n\n"
                "I also hereby revoke the direct debit authorisation I have granted, effective "
                "at the end of the contract. I request a pro-rata refund of any amounts already "
                "paid in advance for the period after the contract end date.\n\n"
                "Kind regards,\n"
                "Angelina Arendt"
            ),
        },

        # ── ticket_3917 GERMAN (exact original text from file) ────────────────
        {
            "key": "3917_de",
            "number": max_num + 2,
            "subject": "Kündigung gemäß Gesetz für fairere Verbraucherverträge",
            "email": "angelina.arendt@gmail.com",
            "name": "Angelina Arendt",
            "category": "refund_request",
            "language": "de",
            "priority": "high",
            "tags": ["subscription-cancellation", "legal-reference", "ai-draft", "bgb-309"],
            "body": (
                "Guten Tag,\n\n"
                "Nach dem Gesetz für fairere Verbraucherverträge ist eine stillschweigende "
                "Vertragsverlängerung noch gültig, wenn die Verbraucher:innen eine Kündigungsfrist "
                "von höchstens einem Monat erhalten.\n"
                "Der Vertrag wurde nach dem 01.03.2022 abgeschlossen somit gilt das Gesetz für "
                "diesen Vertrag.\n\n"
                "hiermit kündige ich meinen Vertrag bei StudyFlash "
                "(Account: angelina.arendt@gmail.com) zum nächstmöglichen Zeitpunkt.\n"
                "Da sich mein Vertrag nach Ablauf der Mindestlaufzeit automatisch verlängert hat, "
                "mache ich von meinem gesetzlichen Kündigungsrecht mit einer Frist von einem Monat "
                "gemäß § 309 Nr. 9 BGB Gebrauch.\n\n"
                "Bitte bestätigen Sie mir den Erhalt dieser Kündigung sowie das genaue "
                "Vertragsenddatum zeitnah per E-Mail.\n\n"
                "Zudem widerrufe ich hiermit die Ihnen erteilte Einzugsermächtigung zum "
                "Vertragsende. Ich bitte Sie, mir den bereits im Voraus gezahlten Betrag für "
                "den Zeitraum nach dem Vertragsende anteilig auf mein Konto zu erstatten.\n\n"
                "Mit freundlichen Grüßen,\n"
                "Angelina Arendt"
            ),
        },

        # ── ticket_3923 Dutch — Klarna charge after prior cancellation request ─
        {
            "key": "3923",
            "number": max_num + 3,
            "subject": "Abonnement annuleren - Klarna afschrijving €30",
            "email": "klarna_user_3923@gmail.com",
            "name": None,
            "category": "refund_request",
            "language": "nl",
            "priority": "high",
            "tags": ["subscription-cancellation", "klarna", "ai-draft", "mobile"],
            "body": (
                "MOBILE: Abbonement annuleren\n\n"
                "Er is 30€ van mijn klarna afgehaald voor een abbonement. "
                "Ik heb al eerder aangegeven dat ik dit abbonement wil stoppen"
            ),
        },

        # ── ticket_4072 Dutch — 2 referrals done, free 30 days not received ───
        {
            "key": "4072",
            "number": max_num + 4,
            "subject": "Gratis 30 dagen nog niet ontvangen na 2 referrals",
            "email": "referral_user_4072@gmail.com",
            "name": None,
            "category": "account",
            "language": "nl",
            "priority": "medium",
            "tags": ["account-issues", "referral", "ai-draft", "free-trial"],
            "body": (
                "ik heb al 2 mensen laten inloggen en krijg nog steeds geen gratis 30 dagen"
            ),
        },

        # ── ticket_4338 German — podcast credits question ─────────────────────
        {
            "key": "4338",
            "number": max_num + 5,
            "subject": "Frage zu Podcast-Credits im Abo",
            "email": "podcast_user_4338@gmail.com",
            "name": None,
            "category": "question",
            "language": "de",
            "priority": "low",
            "tags": ["subscription-info", "credits", "podcasts", "ai-draft"],
            "body": (
                "ist in dem Abo auch das unlimitierte ertellen von Podcasts möglich? "
                "Wie viele Credits benötigt man zum erstellen von Podcats? "
                "wie viele Credits bekommt man im Abo?"
            ),
        },

        # ── ticket_4348 Italian — formal legal dispute, PayPal threat ─────────
        {
            "key": "4348",
            "number": max_num + 6,
            "subject": "Contestazione formale rinnovo automatico abbonamento annuale",
            "email": "gaia.pistone@gmail.com",
            "name": "Gaia Pistone",
            "category": "refund_request",
            "language": "it",
            "priority": "urgent",
            "tags": ["billing-invoice", "auto-renewal", "legal-threat", "paypal-dispute", "ai-draft"],
            "body": (
                "Spett.le Studyflash,\n\n"
                "con la presente intendo contestare formalmente l'addebito relativo al "
                "rinnovo automatico dell'abbonamento annuale a mio carico, avvenuto in data "
                "26/01/2026.\n\n"
                "Preciso che non era mia intenzione rinnovare l'abbonamento e che ritenevo "
                "di aver correttamente disattivato il rinnovo automatico.\n\n"
                "Inoltre, non ho ricevuto alcuna comunicazione preventiva chiara ed esplicita "
                "che mi informasse dell'imminente rinnovo automatico dell'abbonamento, né delle "
                "modalità e dei termini per evitarlo. "
                "Tale mancanza risulta in contrasto con i principi di trasparenza e correttezza "
                "nei contratti a rinnovo automatico, previsti dalla normativa europea e nazionale "
                "a tutela del consumatore, che richiede un'adeguata informativa preventiva prima "
                "dell'addebito.\n\n"
                "Alla luce di quanto sopra, richiedo formalmente:\n"
                "1. L'annullamento immediato del rinnovo automatico dell'abbonamento;\n"
                "2. Il rimborso integrale dell'importo addebitato per il periodo annuale non richiesto;\n"
                "3. Conferma scritta dell'avvenuta cancellazione definitiva dell'abbonamento "
                "e dell'assenza di ulteriori addebiti futuri.\n\n"
                "In mancanza di un riscontro positivo entro 14 giorni dal ricevimento della "
                "presente, mi vedrò costretto ad attivare le procedure di contestazione tramite "
                "PayPal, nonché a valutare ulteriori azioni a tutela dei miei diritti di "
                "consumatore presso le autorità competenti.\n\n"
                "Resto in attesa di un vostro cortese e sollecito riscontro.\n\n"
                "Cordiali saluti,\n"
                "Gaia Pistone\n"
                "numero ricevuta 2426-9559"
            ),
        },
    ]

    ticket_ids = {}
    for t in TICKETS:
        tid = str(uuid.uuid4())
        ticket_ids[t["key"]] = tid
        created = now(-random.randint(1, 72))  # 1-72 hours ago

        cur.execute("""
            INSERT INTO tickets (
                id, ticket_number, subject, sender_email, sender_name,
                status, priority, category, detected_language, tags,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                'open', %s, %s, %s, %s,
                %s, %s
            )
            ON CONFLICT DO NOTHING
        """, (
            tid, t["number"], t["subject"], t["email"], t["name"],
            t["priority"], t["category"], t["language"], json.dumps(t["tags"]),
            created, created,
        ))

        # Insert the message
        cur.execute("""
            INSERT INTO messages (
                id, ticket_id, sender_email, sender_name,
                body_text, direction, source, created_at
            ) VALUES (gen_random_uuid(), %s, %s, %s, %s, 'inbound', 'outlook', %s)
        """, (tid, t["email"], t["name"], t["body"], created))

        lang_flag = {"en": "🇬🇧", "de": "🇩🇪", "nl": "🇳🇱", "it": "🇮🇹"}.get(t["language"], "🌐")
        print(f"  {lang_flag} Ticket #{t['number']} [{t['category']}] — {t['subject'][:55]}")

    conn.commit()
    print(f"  ✓ {len(TICKETS)} tickets inserted")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Insert mock enrichment data for each ticket
# ═══════════════════════════════════════════════════════════════════════════════

print("\n── STEP 3: Inserting mock enrichment data ──────────────────────────")

# Mock SF user data — what _fetch_sf_user_data would return from the real DB
SF_USER_DATA = {
    "angelina.arendt@gmail.com": {
        "id": str(uuid.uuid4()),
        "email": "angelina.arendt@gmail.com",
        "plan": "Pro Annual",
        "created_at": iso(now(-24 * 420)),
        "last_active": iso(now(-24 * 62)),
        "refund_count": 0,
        "stripe_customer_id": "cus_ArenDT9182jX",
    },
    "klarna_user_3923@gmail.com": {
        "id": str(uuid.uuid4()),
        "email": "klarna_user_3923@gmail.com",
        "plan": "Pro Monthly",
        "created_at": iso(now(-24 * 180)),
        "last_active": iso(now(-24 * 14)),
        "refund_count": 1,
        "stripe_customer_id": "cus_KLarn3923mx",
    },
    "referral_user_4072@gmail.com": {
        "id": str(uuid.uuid4()),
        "email": "referral_user_4072@gmail.com",
        "plan": "Free",
        "created_at": iso(now(-24 * 45)),
        "last_active": iso(now(-24 * 3)),
        "refund_count": 0,
        "stripe_customer_id": None,
    },
    "podcast_user_4338@gmail.com": {
        "id": str(uuid.uuid4()),
        "email": "podcast_user_4338@gmail.com",
        "plan": "Pro Annual",
        "created_at": iso(now(-24 * 90)),
        "last_active": iso(now(-24 * 1)),
        "refund_count": 0,
        "stripe_customer_id": "cus_Pod4338deXQ",
    },
    "gaia.pistone@gmail.com": {
        "id": str(uuid.uuid4()),
        "email": "gaia.pistone@gmail.com",
        "plan": "Pro Annual",
        "created_at": iso(now(-24 * 730)),
        "last_active": iso(now(-24 * 44)),
        "refund_count": 0,
        "stripe_customer_id": "cus_GaiPis7301it",
    },
}

# Mock Sentry events — realistic error titles per user
SENTRY_EVENTS = {
    "angelina.arendt@gmail.com": [],  # no errors — clean user
    "klarna_user_3923@gmail.com": [
        {
            "id": "sentry_evt_0012a",
            "title": "PaymentMethodError: Klarna payment_intent failed",
            "dateCreated": iso(now(-24 * 15)),
        },
        {
            "id": "sentry_evt_0012b",
            "title": "SubscriptionUpdateError: Failed to downgrade plan",
            "dateCreated": iso(now(-24 * 16)),
        },
    ],
    "referral_user_4072@gmail.com": [
        {
            "id": "sentry_evt_0034a",
            "title": "ReferralRewardError: reward_grant timed out after 30s",
            "dateCreated": iso(now(-24 * 4)),
        },
    ],
    "podcast_user_4338@gmail.com": [],  # no errors
    "gaia.pistone@gmail.com": [
        {
            "id": "sentry_evt_0078a",
            "title": "SubscriptionRenewalNoticeError: email_send failed for renewal notice",
            "dateCreated": iso(now(-24 * 47)),
        },
    ],
}

# Mock PostHog session recordings
POSTHOG_RECORDINGS = {
    "angelina.arendt@gmail.com": [
        {
            "id": "rec_arendt_01",
            "start_time": iso(now(-24 * 63)),
            "duration": 412,
            "url": "https://app.posthog.com/recordings/rec_arendt_01",
        },
    ],
    "klarna_user_3923@gmail.com": [
        {
            "id": "rec_klarna_01",
            "start_time": iso(now(-24 * 15)),
            "duration": 88,
            "url": "https://app.posthog.com/recordings/rec_klarna_01",
        },
        {
            "id": "rec_klarna_02",
            "start_time": iso(now(-24 * 30)),
            "duration": 247,
            "url": "https://app.posthog.com/recordings/rec_klarna_02",
        },
    ],
    "referral_user_4072@gmail.com": [
        {
            "id": "rec_ref_01",
            "start_time": iso(now(-24 * 3)),
            "duration": 195,
            "url": "https://app.posthog.com/recordings/rec_ref_01",
        },
        {
            "id": "rec_ref_02",
            "start_time": iso(now(-24 * 5)),
            "duration": 320,
            "url": "https://app.posthog.com/recordings/rec_ref_02",
        },
    ],
    "podcast_user_4338@gmail.com": [
        {
            "id": "rec_pod_01",
            "start_time": iso(now(-24 * 1)),
            "duration": 534,
            "url": "https://app.posthog.com/recordings/rec_pod_01",
        },
    ],
    "gaia.pistone@gmail.com": [
        {
            "id": "rec_gaia_01",
            "start_time": iso(now(-24 * 45)),
            "duration": 623,
            "url": "https://app.posthog.com/recordings/rec_gaia_01",
        },
        {
            "id": "rec_gaia_02",
            "start_time": iso(now(-24 * 50)),
            "duration": 189,
            "url": "https://app.posthog.com/recordings/rec_gaia_02",
        },
    ],
}

# Similar past tickets — what the pipeline would find after a few weeks of data
SIMILAR_TICKETS = {
    "3917_en": [
        {"ticket_id": "SF-881", "score": 0.94,
         "reason": "Annual plan auto-renewal cancellation citing BGB § 309 — resolved by confirming cancellation and processing pro-rata refund"},
        {"ticket_id": "SF-762", "score": 0.81,
         "reason": "User invoked Fair Consumer Contracts Act to cancel — agent confirmed 1-month notice period and end date"},
    ],
    "3917_de": [
        {"ticket_id": "SF-881", "score": 0.95,
         "reason": "Automatische Verlängerung Jahresabo mit BGB § 309 Verweis — anteilige Rückerstattung nach Bestätigung"},
        {"ticket_id": "SF-762", "score": 0.82,
         "reason": "Gesetz für fairere Verträge Kündigung — Agent bestätigte Kündigungsdatum per E-Mail"},
    ],
    "3923": [
        {"ticket_id": "SF-904", "score": 0.88,
         "reason": "Klarna charge dispute for monthly plan — refunded after verifying prior cancellation request was not processed"},
        {"ticket_id": "SF-831", "score": 0.72,
         "reason": "Dutch user charged after cancellation request — resolved with full refund"},
    ],
    "4072": [
        {"ticket_id": "SF-720", "score": 0.91,
         "reason": "Referral reward not triggered — bug in reward_grant job; manually credited 30 days Pro"},
        {"ticket_id": "SF-698", "score": 0.77,
         "reason": "2 referrals completed but trial not applied — workaround: manually grant via admin panel"},
    ],
    "4338": [
        {"ticket_id": "SF-650", "score": 0.85,
         "reason": "Pro plan podcast credits question — answered: 10 credits/month, 1 credit per podcast episode"},
        {"ticket_id": "SF-571", "score": 0.73,
         "reason": "Credits usage inquiry — agent explained credit refresh schedule and podcast limits"},
    ],
    "4348": [
        {"ticket_id": "SF-912", "score": 0.93,
         "reason": "Italian user formal renewal dispute, receipt number cited — full refund approved to avoid PayPal dispute"},
        {"ticket_id": "SF-844", "score": 0.86,
         "reason": "Annual renewal without prior notice claim — agent processed refund and sent cancellation confirmation"},
    ],
}

with psycopg.connect(**SUPPORT_DB) as conn:
    cur = conn.cursor()

    for key, tid in ticket_ids.items():
        email = next(t["email"] for t in TICKETS if t["key"] == key)

        sf_data = SF_USER_DATA.get(email)
        sentry = SENTRY_EVENTS.get(email, [])
        posthog = POSTHOG_RECORDINGS.get(email, [])
        similar = SIMILAR_TICKETS.get(key, [])

        cur.execute("""
            INSERT INTO ticket_enrichments (
                id, ticket_id,
                sf_user_data, sentry_events, posthog_recordings, similar_tickets,
                fetched_at, updated_at
            ) VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (ticket_id) DO UPDATE SET
                sf_user_data = EXCLUDED.sf_user_data,
                sentry_events = EXCLUDED.sentry_events,
                posthog_recordings = EXCLUDED.posthog_recordings,
                similar_tickets = EXCLUDED.similar_tickets,
                updated_at = NOW()
        """, (
            tid,
            json.dumps(sf_data),
            json.dumps(sentry),
            json.dumps(posthog),
            json.dumps(similar),
        ))

        sentry_count = len(sentry)
        posthog_count = len(posthog)
        similar_count = len(similar)
        plan = sf_data["plan"] if sf_data else "?"
        print(f"  Enrichment [{key}]: plan={plan} | "
              f"sentry={sentry_count} | posthog={posthog_count} | similar={similar_count}")

    conn.commit()
    print("  ✓ Enrichment data inserted for all tickets")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Insert mock AI drafts so the dashboard shows them immediately
#           (without needing to run the Celery pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

print("\n── STEP 4: Inserting mock AI drafts ────────────────────────────────")

AI_DRAFTS = {
    "3917_en": {
        "body": (
            "Dear Angelina,\n\n"
            "Thank you for your message. I have received your cancellation notice "
            "and confirm that we will process it in accordance with § 309 No. 9 BGB "
            "and the Fair Consumer Contracts Act.\n\n"
            "Your contract will end on [DATE — 1 month from today]. I can confirm "
            "that the direct debit authorisation has been revoked effective from that date, "
            "and that any pro-rata amount paid in advance for the period after the contract "
            "end date will be refunded within 3–5 business days.\n\n"
            "You will receive a formal written confirmation of the cancellation date by "
            "separate email shortly.\n\n"
            "Kind regards,\n"
            "Studyflash Support Team"
        ),
        "confidence": 0.91,
        "model": "llama-3.3-70b-versatile",
    },
    "3917_de": {
        "body": (
            "Guten Tag Angelina,\n\n"
            "vielen Dank für Ihre Nachricht. Wir bestätigen den Erhalt Ihrer Kündigung "
            "gemäß § 309 Nr. 9 BGB und dem Gesetz für fairere Verbraucherverträge.\n\n"
            "Ihr Vertrag endet zum [DATUM — 1 Monat ab heute]. Wir bestätigen, dass die "
            "Einzugsermächtigung zum Vertragsende widerrufen ist und der anteilig bereits "
            "gezahlte Betrag für den Zeitraum nach dem Vertragsende innerhalb von 3–5 "
            "Werktagen auf Ihr Konto zurückerstattet wird.\n\n"
            "Eine schriftliche Kündigungsbestätigung mit dem genauen Enddatum erhalten "
            "Sie in Kürze per separater E-Mail.\n\n"
            "Mit freundlichen Grüßen,\n"
            "Studyflash Support Team"
        ),
        "confidence": 0.93,
        "model": "llama-3.3-70b-versatile",
    },
    "3923": {
        "body": (
            "Beste klant,\n\n"
            "Bedankt voor uw bericht. We zien in uw account dat u eerder al een verzoek "
            "heeft ingediend om uw abonnement te stoppen — het spijt ons dat dit niet "
            "correct verwerkt is.\n\n"
            "We hebben de afschrijving van €30 via Klarna gecontroleerd en zullen dit "
            "bedrag volledig terugstorten. De terugbetaling is binnen 3–5 werkdagen "
            "zichtbaar op uw Klarna-account. Uw abonnement is per direct geannuleerd "
            "en er zullen geen verdere kosten in rekening worden gebracht.\n\n"
            "Onze excuses voor het ongemak.\n\n"
            "Met vriendelijke groeten,\n"
            "Studyflash Support Team"
        ),
        "confidence": 0.87,
        "model": "llama-3.3-70b-versatile",
    },
    "4072": {
        "body": (
            "Beste,\n\n"
            "Bedankt voor uw bericht. We zien in ons systeem dat uw 2 referrals "
            "inderdaad succesvol hebben ingelogd, maar dat de gratis 30-dagenbeloning "
            "nog niet is toegekend — dit is een bekend probleem in ons beloningssysteem "
            "dat we momenteel onderzoeken.\n\n"
            "We hebben de 30 gratis dagen handmatig aan uw account toegevoegd. "
            "U kunt dit controleren door opnieuw in te loggen op de app.\n\n"
            "Onze excuses voor de vertraging en bedankt voor het delen van Studyflash "
            "met uw vrienden!\n\n"
            "Met vriendelijke groeten,\n"
            "Studyflash Support Team"
        ),
        "confidence": 0.82,
        "model": "llama-3.3-70b-versatile",
    },
    "4338": {
        "body": (
            "Hallo,\n\n"
            "vielen Dank für Ihre Frage zu unserem Pro-Abo.\n\n"
            "Im Pro-Abo erhalten Sie monatlich 10 Credits. Für die Erstellung eines "
            "Podcast-Episoden-Skripts wird 1 Credit benötigt. Das Erstellen von Podcasts "
            "ist daher nicht unbegrenzt möglich, sondern auf die monatlich enthaltenen "
            "Credits beschränkt — es gibt jedoch die Möglichkeit, zusätzliche Credit-Pakete "
            "zu erwerben.\n\n"
            "Weitere Details finden Sie in unserem Help Center: https://help.studyflash.ch\n\n"
            "Mit freundlichen Grüßen,\n"
            "Studyflash Support Team"
        ),
        "confidence": 0.88,
        "model": "llama-3.3-70b-versatile",
    },
    "4348": {
        "body": (
            "Gentile Gaia,\n\n"
            "La ringraziamo per averci contattato e ci scusiamo sinceramente per "
            "l'inconveniente causato dal rinnovo automatico del suo abbonamento.\n\n"
            "Abbiamo verificato il suo account (ricevuta n. 2426-9559) e comprendiamo "
            "che il rinnovo del 26/01/2026 non era nelle sue intenzioni. In considerazione "
            "di quanto segnalato — e in particolare della mancata ricezione di una "
            "comunicazione preventiva adeguata — procederemo con il rimborso integrale "
            "dell'importo addebitato entro 3–5 giorni lavorativi.\n\n"
            "Le confermiamo inoltre:\n"
            "• La cancellazione definitiva del rinnovo automatico;\n"
            "• L'assenza di qualsiasi addebito futuro sul suo account.\n\n"
            "Riceverà una conferma scritta separata via email.\n\n"
            "Cordiali saluti,\n"
            "Il team di supporto Studyflash"
        ),
        "confidence": 0.89,
        "model": "llama-3.3-70b-versatile",
    },
}

with psycopg.connect(**SUPPORT_DB) as conn:
    cur = conn.cursor()

    for key, draft in AI_DRAFTS.items():
        tid = ticket_ids[key]
        cur.execute("""
            INSERT INTO ai_drafts (
                id, ticket_id, draft_body, confidence, model_used,
                prompt_tokens, completion_tokens, was_accepted, was_edited, created_at
            ) VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, NULL, FALSE, NOW())
            ON CONFLICT (ticket_id) DO UPDATE SET
                draft_body = EXCLUDED.draft_body,
                confidence = EXCLUDED.confidence
        """, (tid, draft["body"], draft["confidence"], draft["model"],
              random.randint(1800, 2800), random.randint(200, 400)))

        lang = next(t["language"] for t in TICKETS if t["key"] == key)
        flag = {"en": "🇬🇧", "de": "🇩🇪", "nl": "🇳🇱", "it": "🇮🇹"}.get(lang, "🌐")
        print(f"  {flag} Draft [{key}]: confidence={draft['confidence']} | {draft['body'][:60]}…")

    conn.commit()
    print("  ✓ AI drafts inserted for all tickets")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Update .env to point at the mock SF database
# ═══════════════════════════════════════════════════════════════════════════════

print("\n── STEP 5: Updating .env ───────────────────────────────────────────")

env_path = ".env"
try:
    with open(env_path, "r") as f:
        env_content = f.read()

    # Update or insert SF_DATABASE_URL
    mock_url = "postgresql+psycopg://postgres:password@localhost:5433/studyflash_mock"
    if "SF_DATABASE_URL=" in env_content:
        import re
        env_content = re.sub(
            r"SF_DATABASE_URL=.*",
            f"SF_DATABASE_URL={mock_url}",
            env_content
        )
    else:
        env_content += f"\nSF_DATABASE_URL={mock_url}\n"

    with open(env_path, "w") as f:
        f.write(env_content)
    print(f"  ✓ SF_DATABASE_URL updated to: {mock_url}")
except FileNotFoundError:
    print(f"  ⚠ .env not found — set this manually:")
    print(f"    SF_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5433/studyflash_mock")


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "═" * 60)
print("✓ SEED COMPLETE")
print("═" * 60)
print(f"\n  Tickets inserted: {len(TICKETS)}")
print("    🇬🇧 #" + str(max_num+1) + " Angelina Arendt — EN (translated from DE)")
print("    🇩🇪 #" + str(max_num+2) + " Angelina Arendt — DE (original)")
print("    🇳🇱 #" + str(max_num+3) + " Klarna user    — NL subscription cancellation")
print("    🇳🇱 #" + str(max_num+4) + " Referral user  — NL free trial not received")
print("    🇩🇪 #" + str(max_num+5) + " Podcast user   — DE credits question")
print("    🇮🇹 #" + str(max_num+6) + " Gaia Pistone   — IT formal dispute")
print(f"\n  Mock SF database: studyflash_mock")
print("    5 users with plan, billing, refund history")
print(f"\n  Enrichment: all 6 tickets have")
print("    sf_user_data, sentry_events, posthog_recordings, similar_tickets")
print(f"\n  AI drafts: all 6 tickets — ready to use in the dashboard")
print("\n  Next step: restart FastAPI so it reads the updated .env")
print("    python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
