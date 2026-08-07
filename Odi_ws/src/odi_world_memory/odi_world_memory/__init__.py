import mysql.connector

conn = mysql.connector.connect(
    host = "localhost",
    user = "ksj",
    password = "1234",
    database  = "robot_diary"
)

print("connect success!")

conn.close()