/**
 * Structured (JSON) logging, matching the style used by the Python ML
 * service so logs from both processes are consistently shaped.
 */
const LEVELS = { error: 0, warn: 1, info: 2, debug: 3 };

function makeLogger(minLevel) {
  const threshold = LEVELS[minLevel] ?? LEVELS.info;

  function log(level, message, fields = {}) {
    if (LEVELS[level] > threshold) return;
    const payload = {
      timestamp: new Date().toISOString(),
      level: level.toUpperCase(),
      logger: "gateway",
      message,
      ...fields,
    };
    // eslint-disable-next-line no-console
    console.log(JSON.stringify(payload));
  }

  return {
    error: (message, fields) => log("error", message, fields),
    warn: (message, fields) => log("warn", message, fields),
    info: (message, fields) => log("info", message, fields),
    debug: (message, fields) => log("debug", message, fields),
  };
}

module.exports = { makeLogger };
