// Vercel build step: writes config.js with the API's address (the Cloud Run URL in VITE_API_BASE).
const fs = require("fs");
const apiBase = (process.env.VITE_API_BASE || "http://localhost:8080").replace(/\/+$/, "");
fs.writeFileSync("config.js", `window.VITE_API_BASE = ${JSON.stringify(apiBase)};\n`);
console.log(`config.js -> ${apiBase}`);
