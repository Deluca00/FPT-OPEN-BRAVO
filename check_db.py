import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(host='localhost', database='openbravo', user='postgres', password='postgres', port=5432, cursor_factory=RealDictCursor)
cur = conn.cursor()

print("=== M_MOVEMENT COLUMNS ===")
cur.execute("""SELECT column_name FROM information_schema.columns WHERE table_name = 'm_movement' ORDER BY ordinal_position""")
for r in cur.fetchall():
    print(r['column_name'])

print("\n=== M_MOVEMENTLINE COLUMNS ===")
cur.execute("""SELECT column_name FROM information_schema.columns WHERE table_name = 'm_movementline' ORDER BY ordinal_position""")
for r in cur.fetchall():
    print(r['column_name'])

conn.close()
