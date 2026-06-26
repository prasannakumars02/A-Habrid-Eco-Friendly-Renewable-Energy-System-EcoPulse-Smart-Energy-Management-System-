const express = require("express");
const { SerialPort, ReadlineParser } = require("serialport");
const http = require("http");
const socketIo = require("socket.io");

const app = express();
const server = http.createServer(app);
const io = socketIo(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST'],
    credentials: false
  },
  transports: ['websocket', 'polling']
});

let port = null;
let parser = null;
const SERIAL_PATH = process.env.SERIAL_PATH || "COM20";
const SERIAL_BAUD = parseInt(process.env.SERIAL_BAUD || "9600", 10);

// small state used by the flexible parser
let partialSensor = {};
let sawAnySerialData = false;
const kvRegex = /([A-Za-z.\s]+)=\s*([-+]?[0-9]*\.?[0-9]+)/g;

let emitTimer = null;
const EMIT_DELAY_MS = parseInt(process.env.SERIAL_EMIT_DELAY_MS || "500", 10);

// cache last known environment readings so we can include them even if
// current emission window did not receive them yet
let lastTemp = null;
let lastHum = null;

function resetPartial() {
  partialSensor = {
    solar: {},
    wind: {},
    other: {},
    temperature: null,
    humidity: null,
    totalPower: null
  };
}

resetPartial();

function buildAndEmitIfComplete(forceEmit = false) {
  const s = partialSensor.solar;
  const w = partialSensor.wind;
  const o = partialSensor.other;
  const temp = partialSensor.temperature;
  const hum = partialSensor.humidity;

  // compute missing component powers if voltage+current present
  if ((s.voltage != null) && (s.current != null) && s.power == null) s.power = +(s.voltage * s.current).toFixed(2);
  if ((w.voltage != null) && (w.current != null) && w.power == null) w.power = +(w.voltage * w.current).toFixed(2);
  if ((o.voltage != null) && (o.current != null) && o.power == null) o.power = +(o.voltage * o.current).toFixed(2);

  // compute total if device didn't provide it but components exist
  if (partialSensor.totalPower == null) {
    const pS = Number.isFinite(s.power) ? s.power : 0;
    const pW = Number.isFinite(w.power) ? w.power : 0;
    const pO = Number.isFinite(o.power) ? o.power : 0;
    const sum = pS + pW + pO;
    if (pS || pW || pO) {
      partialSensor.totalPower = +sum.toFixed(2);
      console.log('Computed totalPower:', partialSensor.totalPower);
    }
  }

  const hasComponent = (Object.keys(s).length || Object.keys(w).length || Object.keys(o).length);
  const hasSome = hasComponent || temp != null || hum != null || partialSensor.totalPower != null;
  if (!hasSome) return;

  // Use last known env readings if current batch doesn't include them
  const emitTemp = (temp != null ? temp : lastTemp);
  const emitHum = (hum != null ? hum : lastHum);

  // If forced (debounce expiry) or we have env readings (current or cached), emit
  if (forceEmit || (emitTemp != null && emitHum != null)) {
    const out = {
      solar: s,
      wind: w,
      other: o,
      temperature: emitTemp,
      humidity: emitHum,
      totalPower: partialSensor.totalPower
    };
    latest_sensor_data = out; // Store for REST API
    io.emit("sensorData", out);
    console.log("→ Sent:", out);
    resetPartial();
  } else {
    console.log('Not emitting yet — waiting for more fields, current state:', {
      solar: s, wind: w, other: o, temperature: temp, humidity: hum, totalPower: partialSensor.totalPower
    });
  }
}

function attachSerial(p) {
  parser = p.pipe(new ReadlineParser({ delimiter: "\n" }));
  parser.on("data", (line) => {
    const text = String(line).trim();
    if (!text) return;

    // ignore separators and pure punctuation lines
    if (/^[-_=*]{3,}$/.test(text) || /^[\W_]+$/.test(text)) return;

    console.log("Serial RAW:", text);

    // CSV fallback: immediate emit for well-formed 11-value lines
    const values = text.split(",").map(v => v.trim()).filter(v => v !== "");
    if (values.length === 11) {
      const data = {
        solar: { voltage: +values[0], current: +values[1], power: +values[2] },
        wind:  { voltage: +values[3], current: +values[4], power: +values[5] },
        other: { voltage: +values[6], current: +values[7], power: +values[8] },
        temperature: +values[9],
        humidity: +values[10],
        totalPower: null
      };
      latest_sensor_data = data; // Store for REST API
      io.emit("sensorData", data);
      console.log("→ Sent (CSV):", data);
      return;
    }

    // flexible key=value parsing using matchAll (stateless)
    // Match patterns like: Temp=26.2°C, S.V=0.9, Hum=28.0%, Total Power=-10.5 W
    const kvRe = /([A-Za-z\.\s]+?)=\s*([-+]?[0-9]*\.?[0-9]+)/g;
    let matched = false;
    for (const m of text.matchAll(kvRe)) {
    matched = true;
    const rawKey = m[1].trim();

    // Remove units like °C, %, W, V etc. from numeric part
    const cleaned = m[2].replace(/[^\d.-]/g, "");
    const num = parseFloat(cleaned);

      if (Number.isNaN(num)) continue;

      const key = rawKey.replace(/\s+/g, "").toLowerCase();

      if (key.length > 0 && /[swo]/.test(key[0])) {
        const compMap = { s: "solar", w: "wind", o: "other" };
        const comp = compMap[key[0]];
        if (key.includes("v")) partialSensor[comp].voltage = num;
        if (key.includes("c")) partialSensor[comp].current = num;
        if (key.includes("p")) partialSensor[comp].power = num;
      } else if (key.startsWith("temp")) {
        partialSensor.temperature = num;
        lastTemp = num;
      } else if (key.startsWith("hum")) {
        partialSensor.humidity = num;
        lastHum = num;
      } else if (key.startsWith("total")) {
        partialSensor.totalPower = num;
        console.log('Parsed totalPower from device:', partialSensor.totalPower);
      }
      sawAnySerialData = true;
    }

    if (matched) {
      // Debounce emission: collect lines within EMIT_DELAY_MS, then emit once
      if (emitTimer) clearTimeout(emitTimer);
      emitTimer = setTimeout(() => {
        buildAndEmitIfComplete(true);
        emitTimer = null;
      }, EMIT_DELAY_MS);
    } else {
      console.log("Serial line received but did not match expected formats:", text);
    }
  });
}

// --- Mock emitter when serial is not available ---
let mockInterval = null;
function startMockEmitter() {
  if (mockInterval) return;
  console.log('Starting mock sensor emitter (no serial)');
  mockInterval = setInterval(() => {
    const solarV = +(Math.random() * 50 + 200).toFixed(2);
    const solarI = +(Math.random() * 10 + 1).toFixed(2);
    const solarP = +(solarV * solarI).toFixed(2);

    const windV = +(Math.random() * 30 + 100).toFixed(2);
    const windI = +(Math.random() * 5 + 0.5).toFixed(2);
    const windP = +(windV * windI).toFixed(2);

    const otherV = +(Math.random() * 20 + 50).toFixed(2);
    const otherI = +(Math.random() * 3 + 0.2).toFixed(2);
    const otherP = +(otherV * otherI).toFixed(2);

    const temperature = +(Math.random() * 10 + 20).toFixed(2);
    const humidity = +(Math.random() * 40 + 30).toFixed(2);

    const data = {
      solar: { voltage: solarV, current: solarI, power: solarP },
      wind: { voltage: windV, current: windI, power: windP },
      other: { voltage: otherV, current: otherI, power: otherP },
      temperature,
      humidity,
    };
    io.emit('sensorData', data);
    console.log('→ Mock Sent:', data);
  }, 1000);
}

function stopMockEmitter() {
  if (mockInterval) {
    clearInterval(mockInterval);
    mockInterval = null;
    console.log('Stopped mock sensor emitter');
  }
}

function tryOpenSerial() {
  try {
    // create port handle (autoOpen: false so we control when it opens)
    port = new SerialPort({ path: SERIAL_PATH, baudRate: SERIAL_BAUD, autoOpen: false });

    port.open((err) => {
      if (err) {
        console.log(`Failed to open serial port ${SERIAL_PATH}:`, err.message || err);
        port = null;
        return;
      }
      console.log(`Serial port opened: ${SERIAL_PATH} @ ${SERIAL_BAUD}`);
      // stop mock now that serial is open and attach parser
      stopMockEmitter();
      attachSerial(port);

      port.on('close', () => {
        console.log(`Serial port ${SERIAL_PATH} closed`);
        port = null;
        // restart mock emitter to keep frontend alive
        startMockEmitter();
      });
    });

    port.on('error', (err) => {
      console.log(`Serial port error (${SERIAL_PATH}):`, err.message || err);
      // common message for access denied includes "access" or "permission"
      if (err.message && /access|permission|denied/i.test(err.message)) {
        console.log(`Access denied for ${SERIAL_PATH}. Ensure no other program (Arduino IDE serial monitor) has it open.`);
        port = null;
      }
    });
  } catch (e) {
    console.log('serialport module not available or failed to initialize:', e.message || e);
    port = null;
  }
}

const DISABLE_MOCK = (process.env.DISABLE_MOCK === '1' || process.env.DISABLE_MOCK === 'true');

// Attempt to open serial immediately
tryOpenSerial();

// If serial not available right away, run mock emitter so frontend still gets data
if ((!port || !port.isOpen) && !DISABLE_MOCK) {
  startMockEmitter();
} else if (DISABLE_MOCK) {
  console.log('Mock emitter disabled via DISABLE_MOCK=1');
}

// If serial not open, try to reconnect every 5 seconds
const serialRetryInterval = setInterval(() => {
  if (!port || !port.isOpen) {
    console.log('Retrying serial port connection...');
    tryOpenSerial();
  }
}, 5000);

// Add basic server error handler (optional)
const PORT = parseInt(process.env.PORT || "3000", 10);
// --- REST API endpoint for latest sensor data ---
app.get('/api/sensor-data', (req, res) => {
  if (!latest_sensor_data || Object.keys(latest_sensor_data).length === 0) {
    return res.json({ status: 'waiting' });
  }
  res.json(latest_sensor_data);
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Store latest data for REST API
let latest_sensor_data = {};

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Port ${PORT} already in use. Kill process using it or set PORT to a different value.`);
    process.exit(1);
  }
});
server.listen(PORT, () => {
  console.log(`✅ Server running at http://localhost:${PORT}`);
});

io.on('connection', (socket) => {
  console.log('✅ Socket.IO client connected:', socket.id);
  socket.on('disconnect', () => console.log('Socket.IO client disconnected:', socket.id));
});
