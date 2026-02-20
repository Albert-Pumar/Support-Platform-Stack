import psycopg
import uuid

conn = psycopg.connect(
    host="127.0.0.1",
    port=5433,
    dbname="studyflash_support",
    user="postgres",
    password="password"
)

cur = conn.cursor()

# Generate a ticket ID so we can reference it for the message
ticket_id = str(uuid.uuid4())
ticket_number = 2  # change to 3, 4 etc if you already inserted ticket 2

# Insert the ticket
cur.execute(
    """
    INSERT INTO tickets (
        id, ticket_number, subject, sender_email, sender_name,
        status, priority, tags, created_at, updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s,
        'open', 'medium', '[]', NOW(), NOW()
    )
    """,
    (ticket_id, ticket_number, "Refund request - Pro Plan renewal", "anna.mueller@gmail.com", "Anna Mueller")
)

# Insert a message for the ticket (the AI needs this to generate a draft)
cur.execute(
    """
    INSERT INTO messages (
        id, ticket_id, sender_email, sender_name,
        body_text, direction, source, created_at
    )
    VALUES (
        gen_random_uuid(), %s, %s, %s, %s,
        'inbound', 'outlook', NOW()
    )
    """,
    (
        ticket_id,
        "anna.mueller@gmail.com",
        "Anna Mueller",
        "Hello, I was charged for a Pro Plan renewal but I forgot to cancel. "
        "I have not used the app in months and I would like a full refund. "
        "Could you please help me with this? Thank you, Anna"
    )
)

conn.commit()
cur.close()
conn.close()
print("Ticket and message created! Ticket ID: " + ticket_id)