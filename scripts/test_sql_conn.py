
import sqlite3
from spider_agent_workbench.paths import DATABASES_DIR

print (DATABASES_DIR)
db = DATABASES_DIR/ "aircraft"/ "aircraft.sqlite"
print (db)
conn = sqlite3.connect(db)
cursor = conn.execute("select name from sqlite_master where type = 'table' order by name")

tables = [row[0] for row in cursor]
conn.close()
print (tables)
# print (conn.execute("Select Aircraft_ID, Aircraft from aircraft where Aircraft_ID=1").fetchall())
