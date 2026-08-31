import serial, time

ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(2)

print("예: P70 / T30 / q")
while True:
    s = input("> ")
    if s == 'q':
        break
    ser.write(f"{s}\n".encode())
    print(ser.readline().decode().strip())

ser.close()