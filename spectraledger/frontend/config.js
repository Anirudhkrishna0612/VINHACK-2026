/* The ONLY place backend URLs are defined. Change these two lines if a service runs elsewhere.
   The WebSocket URL is derived from AI_ENGINE_URL (http -> ws) in app.js, so it is not duplicated here. */
window.SPECTRA_CONFIG = {
  LEDGER_URL: "http://localhost:8080",     // Java Spring Boot ledger (system of record)
  AI_ENGINE_URL: "http://localhost:8000"   // Python FastAPI AI engine (forecast, agents, order book, live stream)
};
