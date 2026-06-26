import serial
import time

# -------- USER SETTINGS --------
COM_PORT = 'COM20'     # Change to your Arduino COM port (e.g., 'COM4', '/dev/ttyUSB0' for Linux)
BAUD_RATE = 9600      # Must match Arduino Serial.begin(baud rate)
# --------------------------------

try:
    # Initialize serial connection
    arduino = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)  # Wait for Arduino to reset after connection
    print(f"Connected to Arduino on {COM_PORT} at {BAUD_RATE} baud.")
    print("Reading data... Press Ctrl+C to stop.\n")

    while True:
        if arduino.in_waiting > 0:  # Check if data is available
            line = arduino.readline().decode('utf-8').strip()  # Read and decode the line
            if line:  # If line is not empty
                print(f"Arduino says: {line}")

except serial.SerialException:
    print(f"Error: Could not open serial port {COM_PORT}. Check connection and port number.")
except KeyboardInterrupt:
    print("\nStopped by user.")
finally:
    try:
        arduino.close()
        print("Serial connection closed.")
    except:
        pass
