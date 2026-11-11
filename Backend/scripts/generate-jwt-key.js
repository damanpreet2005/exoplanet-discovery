/**
 * Prints a new Ed25519 private key for signing access tokens, as a single
 * .env line (newlines escaped as \n). Run once per environment and store the
 * output in that environment's .env / secret store -- never commit it.
 *
 *   npm run generate:jwt-key            -> JWT_PRIVATE_KEY=... on stdout
 *   npm run generate:jwt-key -- --pem   -> plain PEM (for JWT_PRIVATE_KEY_FILE)
 */
const crypto = require("crypto");

const { privateKey } = crypto.generateKeyPairSync("ed25519");
const pem = privateKey.export({ type: "pkcs8", format: "pem" });

if (process.argv.includes("--pem")) {
  process.stdout.write(pem);
} else {
  process.stdout.write(`JWT_PRIVATE_KEY=${pem.trim().replace(/\n/g, "\\n")}\n`);
}
